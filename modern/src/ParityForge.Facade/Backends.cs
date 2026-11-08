using System.Net.Http.Json;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ParityForge.Facade;

/// <summary>
/// A buffered JSON body. The runners' standard-library servers need a Content-Length,
/// which a streamed JSON body does not send.
/// </summary>
internal static class Json
{
    public static StringContent Body(object value) =>
        new(JsonSerializer.Serialize(value), System.Text.Encoding.UTF8, "application/json");
}

public sealed class FacadeOptions
{
    public string OrchestratorUrl { get; set; } = "http://orchestrator:8000";
    public string CobolRunnerUrl { get; set; } = "http://cobol-runner:9000";
    public string BuilderSocket { get; set; } = "/run/builder/builder.sock";
    public string RunnerToken { get; set; } = "";
    public string FacadeToken { get; set; } = "";
    public int RouteRefreshSeconds { get; set; } = 2;
}

public sealed record GeneratedFile(
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("content")] string Content);

public sealed record ArtifactRef(
    [property: JsonPropertyName("sha256")] string Sha256,
    [property: JsonPropertyName("version")] int Version,
    [property: JsonPropertyName("files")] IReadOnlyList<GeneratedFile> Files);

public sealed record ModuleRoute(
    [property: JsonPropertyName("mode")] string Mode,
    [property: JsonPropertyName("module_id")] string? ModuleId,
    [property: JsonPropertyName("artifact")] ArtifactRef? Artifact);

public sealed record RouteSnapshot(
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("modules")] IReadOnlyDictionary<string, ModuleRoute> Modules)
{
    /// <summary>Before the first successful read, everything goes to the legacy program.</summary>
    public static readonly RouteSnapshot AllLegacy = new("initial", new Dictionary<string, ModuleRoute>());

    public ModuleRoute For(string program) =>
        Modules.TryGetValue(program, out var route) ? route : new ModuleRoute("LEGACY", null, null);
}

public class BackendException(string code) : Exception(code)
{
    public string Code { get; } = code;
}

public interface ILegacyBackend
{
    Task<string> CallAsync(string program, string record, CancellationToken cancellationToken);
}

public interface IModernBackend
{
    Task<string> CallAsync(string program, string record, ArtifactRef artifact, CancellationToken cancellationToken);
}

public interface IShadowReporter
{
    Task ReportAsync(string program, string record, string legacy, string modern, CancellationToken cancellationToken);
}

public interface IRouteSource
{
    Task<RouteSnapshot> FetchAsync(CancellationToken cancellationToken);
}

/// <summary>BRCALL in cobol-runner, one record at a time, with the runner token.</summary>
public sealed class LegacyBackend(HttpClient http) : ILegacyBackend
{
    public async Task<string> CallAsync(string program, string record, CancellationToken cancellationToken)
    {
        using var response = await http.PostAsync($"/v1/brcall/{program}", Json.Body(new { records = new[] { record } }), cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new BackendException("LEGACY_UNAVAILABLE");
        }
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
        var stdout = body.RootElement.GetProperty("stdout").GetString() ?? "";
        var lines = stdout.Split('\n');
        if (body.RootElement.GetProperty("exit_code").GetInt32() != 0 || lines.Length != 2)
        {
            throw new BackendException("LEGACY_RUN_FAILED");
        }
        return lines[0];
    }
}

/// <summary>The approved artifact in dotnet-builder, over its Unix socket, with the runner token.</summary>
public sealed class ModernBackend(HttpClient http) : IModernBackend
{
    public static SocketsHttpHandler UnixSocketHandler(string path) => new()
    {
        ConnectCallback = async (_, cancellationToken) =>
        {
            var socket = new Socket(AddressFamily.Unix, SocketType.Stream, ProtocolType.Unspecified);
            await socket.ConnectAsync(new UnixDomainSocketEndPoint(path), cancellationToken);
            return new NetworkStream(socket, ownsSocket: true);
        },
    };

    public async Task<string> CallAsync(string program, string record, ArtifactRef artifact, CancellationToken cancellationToken)
    {
        using var response = await http.PostAsync("/v1/run", Json.Body(new { files = artifact.Files, records = new[] { record } }), cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new BackendException("MODERN_UNAVAILABLE");
        }
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
        if (!body.RootElement.TryGetProperty("outputs", out var outputs) || outputs.ValueKind != JsonValueKind.Array || outputs.GetArrayLength() != 1)
        {
            throw new BackendException("MODERN_RUN_FAILED");
        }
        return outputs[0].GetString() ?? "";
    }
}

/// <summary>The orchestrator's internal API: the route table, and each shadow comparison.</summary>
public sealed class OrchestratorClient(HttpClient http) : IRouteSource, IShadowReporter
{
    public async Task<RouteSnapshot> FetchAsync(CancellationToken cancellationToken) =>
        await http.GetFromJsonAsync<RouteSnapshot>("/api/v1/internal/facade/routes", cancellationToken)
        ?? throw new BackendException("ROUTES_UNAVAILABLE");

    public async Task ReportAsync(string program, string record, string legacy, string modern, CancellationToken cancellationToken)
    {
        using var response = await http.PostAsJsonAsync(
            "/api/v1/internal/facade/shadow",
            new { program, input = record, legacy, modern },
            cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new BackendException("SHADOW_REPORT_FAILED");
        }
    }
}
