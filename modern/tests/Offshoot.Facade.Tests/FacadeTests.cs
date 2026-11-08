using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Offshoot.Facade;
using Xunit;

namespace Offshoot.Facade.Tests;

public sealed class FakeLegacy : ILegacyBackend
{
    public List<string> Calls { get; } = [];
    public string Answer { get; set; } = "E0000600006000001000000559100425000006016N0000150000006166";

    public Task<string> CallAsync(string program, string record, CancellationToken cancellationToken)
    {
        Calls.Add(record);
        return Task.FromResult(Answer);
    }
}

public sealed class FakeModern : IModernBackend
{
    public List<string> Calls { get; } = [];
    public string Answer { get; set; } = "E0000600006000001000000559000425000006015N0000150000006165";
    public bool Fail { get; set; }

    public Task<string> CallAsync(string program, string record, ArtifactRef artifact, CancellationToken cancellationToken)
    {
        Calls.Add(record);
        return Fail ? throw new BackendException("MODERN_RUN_FAILED") : Task.FromResult(Answer);
    }
}

public sealed class FakeReporter : IShadowReporter
{
    public List<(string Program, string Record, string Legacy, string Modern)> Reports { get; } = [];

    public Task ReportAsync(string program, string record, string legacy, string modern, CancellationToken cancellationToken)
    {
        Reports.Add((program, record, legacy, modern));
        return Task.CompletedTask;
    }
}

public sealed class CodecTests
{
    private static JsonElement Json(string text) => JsonDocument.Parse(text).RootElement;

    [Fact]
    public void Requests_become_the_callrec_input_records()
    {
        Assert.Equal("R1000610", Codecs.Encode("RATECALC", Json("""{"customer_class":"R","month":10,"kwh":610}""")));
        Assert.Equal("+99950+00100A", Codecs.Encode("MTRVAL", Json("""{"previous_read":99950,"current_read":100,"read_type":"A"}""")));
        Assert.Equal("-00001+00000E", Codecs.Encode("MTRVAL", Json("""{"previous_read":-1,"current_read":0,"read_type":"E"}""")));
        Assert.Equal(
            "000020000990101990201N0012345",
            Codecs.Encode("LATEFEE", Json("""{"balance":"200.00","due_date":"990101","bill_date":"990201","senior":false,"credit":"123.45"}""")));
        var statement = Codecs.Encode("STMTGEN", Json("""
            {"customer_id":"NG000001","name":"SAGE PEMBERTON","bill_date":"990930","kwh":400,"estimate_flag":" ",
             "current":"41.75","fee":"0.00","arrears":"0.00","total_due":"41.75"}
            """));
        Assert.Equal("NG000001SAGE PEMBERTON                99093000400 00000417500000000000000000004175", statement);
        Assert.Equal(82, statement.Length);
    }

    [Theory]
    [InlineData("RATECALC", """{"customer_class":"R","month":10}""")]
    [InlineData("RATECALC", """{"customer_class":"RR","month":10,"kwh":5}""")]
    [InlineData("RATECALC", """{"customer_class":"R","month":10,"kwh":100000}""")]
    [InlineData("RATECALC", """{"customer_class":"R","month":"10","kwh":5}""")]
    [InlineData("LATEFEE", """{"balance":"1.005","due_date":"990101","bill_date":"990201","senior":false,"credit":"0"}""")]
    [InlineData("LATEFEE", """{"balance":200.0,"due_date":"990101","bill_date":"990201","senior":false,"credit":"0"}""")]
    [InlineData("LATEFEE", """{"balance":"-1.00","due_date":"990101","bill_date":"990201","senior":false,"credit":"0"}""")]
    [InlineData("LATEFEE", """{"balance":"1.00","due_date":"99-01-01","bill_date":"990201","senior":false,"credit":"0"}""")]
    [InlineData("MTRVAL", """[1,2,3]""")]
    public void Invalid_requests_are_refused_before_any_backend(string program, string body)
    {
        Assert.Throws<RequestError>(() => Codecs.Encode(program, Json(body)));
    }

    [Fact]
    public void Output_records_become_exact_json_values()
    {
        var rate = Codecs.Decode("RATECALC", "E0000600006000001000000559100425000006016N0000150000006166");
        Assert.Equal("55.91", rate["energy"]);
        Assert.Equal("61.66", rate["total"]);
        Assert.Equal(600, rate["tier_limit"]);
        Assert.Equal(false, rate["minimum_applied"]);
        var meter = Codecs.Decode("MTRVAL", "E0000150Y ");
        Assert.Equal(150, meter["consumption_kwh"]);
        Assert.Equal(true, meter["rollover"]);
        Assert.Throws<RecordError>(() => Codecs.Decode("MTRVAL", "!EXCEPTION FormatException"));
    }
}

public sealed class HandlerTests
{
    private static readonly ArtifactRef Artifact = new("abc", 2, [new GeneratedFile("src/ModuleEntry.cs", "x")]);

    private static (BackendHandler Handler, FakeLegacy Legacy, FakeModern Modern, FakeReporter Reporter) Make(string mode = "SHADOW")
    {
        var state = new RouteState();
        state.Set(new RouteSnapshot("v1", new Dictionary<string, ModuleRoute> { ["RATECALC"] = new(mode, "m1", Artifact) }));
        var legacy = new FakeLegacy();
        var modern = new FakeModern();
        var reporter = new FakeReporter();
        return (new BackendHandler(legacy, modern, reporter, state, NullLogger<BackendHandler>.Instance), legacy, modern, reporter);
    }

    private static readonly JsonElement Rate = JsonDocument.Parse("""{"customer_class":"R","month":10,"kwh":610}""").RootElement;

    [Fact]
    public async Task Shadow_runs_both_reports_the_pair_and_answers_with_legacy()
    {
        var (handler, legacy, modern, reporter) = Make();
        var result = await handler.HandleAsync("shadow", "RATECALC", Rate, CancellationToken.None);
        Assert.Equal((200, "shadow"), (result.Status, result.Route));
        Assert.Equal("55.91", ((Dictionary<string, object?>)result.Body)["energy"]);
        Assert.Equal(["R1000610"], legacy.Calls);
        Assert.Equal(["R1000610"], modern.Calls);
        var report = Assert.Single(reporter.Reports);
        Assert.Equal(("RATECALC", "R1000610", legacy.Answer, modern.Answer), report);
    }

    [Fact]
    public async Task A_failing_modern_side_is_reported_and_the_caller_still_gets_legacy()
    {
        var (handler, _, modern, reporter) = Make();
        modern.Fail = true;
        var result = await handler.HandleAsync("shadow", "RATECALC", Rate, CancellationToken.None);
        Assert.Equal(200, result.Status);
        Assert.Equal("!MODERN_RUN_FAILED", Assert.Single(reporter.Reports).Modern);
    }

    [Fact]
    public async Task Legacy_and_modern_call_only_their_own_side()
    {
        var (handler, legacy, modern, reporter) = Make("MODERN");
        var answer = await handler.HandleAsync("modern", "RATECALC", Rate, CancellationToken.None);
        Assert.Equal(("modern", "55.90"), (answer.Route, ((Dictionary<string, object?>)answer.Body)["energy"]));
        Assert.Empty(legacy.Calls);
        await handler.HandleAsync("legacy", "RATECALC", Rate, CancellationToken.None);
        Assert.Single(legacy.Calls);
        Assert.Single(modern.Calls);
        Assert.Empty(reporter.Reports);
    }

    [Fact]
    public async Task Modern_without_an_approved_artifact_is_unavailable()
    {
        var state = new RouteState();
        var handler = new BackendHandler(new FakeLegacy(), new FakeModern(), new FakeReporter(), state, NullLogger<BackendHandler>.Instance);
        var result = await handler.HandleAsync("modern", "RATECALC", Rate, CancellationToken.None);
        Assert.Equal(503, result.Status);
    }

    [Fact]
    public async Task An_invalid_request_reaches_no_backend()
    {
        var (handler, legacy, modern, _) = Make();
        var bad = JsonDocument.Parse("""{"customer_class":"R"}""").RootElement;
        var result = await handler.HandleAsync("shadow", "RATECALC", bad, CancellationToken.None);
        Assert.Equal(422, result.Status);
        Assert.Empty(legacy.Calls);
        Assert.Empty(modern.Calls);
    }

    [Fact]
    public async Task A_modern_record_that_breaks_the_layout_is_a_bad_gateway()
    {
        var (handler, _, modern, _) = Make("MODERN");
        modern.Answer = "!EXCEPTION NullReferenceException";
        var result = await handler.HandleAsync("modern", "RATECALC", Rate, CancellationToken.None);
        Assert.Equal(502, result.Status);
    }
}

public sealed class ProxyConfigTests
{
    [Fact]
    public void Each_public_path_routes_to_its_module_mode()
    {
        var snapshot = new RouteSnapshot("v2", new Dictionary<string, ModuleRoute>
        {
            ["MTRVAL"] = new("MODERN", "a", null),
            ["LATEFEE"] = new("SHADOW", "b", null),
        });
        var routes = ProxyConfig.Routes(snapshot).ToDictionary(route => route.RouteId);
        Assert.Equal("modern", routes["MTRVAL"].ClusterId);
        Assert.Equal("shadow", routes["LATEFEE"].ClusterId);
        Assert.Equal("legacy", routes["RATECALC"].ClusterId);
        Assert.Equal("legacy", routes["STMTGEN"].ClusterId);
        Assert.Equal("/billing/late-fee", routes["LATEFEE"].Match.Path);
        Assert.Equal("/backends/shadow/LATEFEE", routes["LATEFEE"].Transforms![0]["PathSet"]);
        Assert.Equal(3, ProxyConfig.Clusters().Count);
    }

    [Fact]
    public void An_unknown_mode_falls_back_to_legacy()
    {
        var snapshot = new RouteSnapshot("v3", new Dictionary<string, ModuleRoute> { ["MTRVAL"] = new("SIDEWAYS", "a", null) });
        Assert.Equal("legacy", ProxyConfig.Routes(snapshot).Single(route => route.RouteId == "MTRVAL").ClusterId);
    }

    [Fact]
    public void Before_any_table_is_read_everything_is_legacy()
    {
        Assert.All(ProxyConfig.Routes(RouteSnapshot.AllLegacy), route => Assert.Equal("legacy", route.ClusterId));
    }
}

public sealed class FacadeAppFactory : WebApplicationFactory<Program>
{
    public FakeLegacy Legacy { get; } = new();
    public FakeModern Modern { get; } = new();
    public FakeReporter Reporter { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<IHostedService>();
            services.AddSingleton<ILegacyBackend>(Legacy);
            services.AddSingleton<IModernBackend>(Modern);
            services.AddSingleton<IShadowReporter>(Reporter);
        });
    }
}

internal static class ServiceCollectionExtensions
{
    public static void RemoveAll<T>(this IServiceCollection services)
    {
        foreach (var descriptor in services.Where(d => d.ServiceType == typeof(T)).ToList())
        {
            services.Remove(descriptor);
        }
    }
}

public sealed class PipelineTests : IClassFixture<FacadeAppFactory>
{
    private readonly FacadeAppFactory factory;

    public PipelineTests(FacadeAppFactory factory) => this.factory = factory;

    [Fact]
    public async Task The_health_check_answers()
    {
        var response = await factory.CreateClient().GetAsync(new Uri("/healthz", UriKind.Relative), TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Backends_answer_only_on_the_internal_listener()
    {
        var client = factory.CreateClient();
        var body = JsonContent.Create(new { customer_class = "R", month = 10, kwh = 610 });
        var outside = await client.PostAsync(new Uri("/backends/legacy/RATECALC", UriKind.Relative), body, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.NotFound, outside.StatusCode);

        using var inside = new HttpRequestMessage(HttpMethod.Post, "/backends/legacy/RATECALC") { Content = JsonContent.Create(new { customer_class = "R", month = 10, kwh = 610 }) };
        inside.Headers.Host = "127.0.0.1:8081";
        var response = await client.SendAsync(inside, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("legacy", response.Headers.GetValues("X-Offshoot-Route").Single());
        var json = await response.Content.ReadFromJsonAsync<JsonElement>(TestContext.Current.CancellationToken);
        Assert.Equal("55.91", json.GetProperty("energy").GetString());
    }

    [Fact]
    public async Task Malformed_json_is_a_bad_request()
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "/backends/shadow/RATECALC") { Content = new StringContent("{not json", System.Text.Encoding.UTF8, "application/json") };
        request.Headers.Host = "127.0.0.1:8081";
        var response = await factory.CreateClient().SendAsync(request, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }
}
