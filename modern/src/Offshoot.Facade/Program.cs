using System.Text.Json;
using Offshoot.Facade;
using Yarp.ReverseProxy.Configuration;

var builder = WebApplication.CreateBuilder(args);

var options = new FacadeOptions
{
    OrchestratorUrl = Environment.GetEnvironmentVariable("ORCHESTRATOR_URL") ?? "http://orchestrator:8000",
    CobolRunnerUrl = Environment.GetEnvironmentVariable("COBOL_RUNNER_URL") ?? "http://cobol-runner:9000",
    BuilderSocket = Environment.GetEnvironmentVariable("DOTNET_BUILDER_SOCKET") ?? "/run/builder/builder.sock",
    RunnerToken = Environment.GetEnvironmentVariable("RUNNER_SHARED_SECRET") ?? "",
    FacadeToken = Environment.GetEnvironmentVariable("FACADE_SHARED_SECRET") ?? "",
};
builder.Services.AddSingleton(options);
builder.Services.AddSingleton<RouteState>();
builder.Services.AddHttpClient<ILegacyBackend, LegacyBackend>(client =>
{
    client.BaseAddress = new Uri(options.CobolRunnerUrl);
    client.DefaultRequestHeaders.Add("X-Runner-Token", options.RunnerToken);
    client.Timeout = TimeSpan.FromSeconds(60);
});
builder.Services.AddHttpClient<IModernBackend, ModernBackend>(client =>
{
    client.BaseAddress = new Uri("http://dotnet-builder");
    client.DefaultRequestHeaders.Add("X-Runner-Token", options.RunnerToken);
    // The first call to a new artifact builds it in the sandbox.
    client.Timeout = TimeSpan.FromSeconds(300);
}).ConfigurePrimaryHttpMessageHandler(() => ModernBackend.UnixSocketHandler(options.BuilderSocket));
builder.Services.AddHttpClient<OrchestratorClient>(client =>
{
    client.BaseAddress = new Uri(options.OrchestratorUrl);
    client.DefaultRequestHeaders.Add("X-Facade-Token", options.FacadeToken);
    client.Timeout = TimeSpan.FromSeconds(30);
});
builder.Services.AddTransient<IRouteSource>(provider => provider.GetRequiredService<OrchestratorClient>());
builder.Services.AddTransient<IShadowReporter>(provider => provider.GetRequiredService<OrchestratorClient>());
builder.Services.AddTransient<BackendHandler>();
builder.Services.AddHostedService<RouteRefresher>();
builder.Services.AddReverseProxy().LoadFromMemory(ProxyConfig.Routes(RouteSnapshot.AllLegacy), ProxyConfig.Clusters());
builder.WebHost.ConfigureKestrel(kestrel =>
{
    kestrel.ListenAnyIP(8080);
    // The backends are reachable only on loopback, from YARP in this process.
    kestrel.ListenLocalhost(8081);
});

var app = builder.Build();

app.MapGet("/healthz", () => Results.Ok(new { status = "ok" }));
app.MapGet("/routes", (RouteState state) => Results.Ok(new
{
    state.Current.Version,
    modules = state.Current.Modules.ToDictionary(pair => pair.Key, pair => pair.Value.Mode),
}));

app.MapPost("/backends/{mode}/{program}", async (string mode, string program, HttpRequest request, BackendHandler handler, CancellationToken cancellationToken) =>
{
    JsonElement body;
    try
    {
        body = await JsonSerializer.DeserializeAsync<JsonElement>(request.Body, cancellationToken: cancellationToken);
    }
    catch (JsonException)
    {
        return Results.Json(new { error = new { code = "INVALID_JSON", message = "The request body is not JSON." } }, statusCode: 400);
    }
    var result = await handler.HandleAsync(mode, program, body, cancellationToken);
    request.HttpContext.Response.Headers["X-Offshoot-Route"] = result.Route;
    return Results.Json(result.Body, statusCode: result.Status);
}).RequireHost("*:8081");

app.MapReverseProxy();
app.Run();

/// <summary>For the integration tests.</summary>
public partial class Program;
