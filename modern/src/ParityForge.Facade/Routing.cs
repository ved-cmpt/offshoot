using Yarp.ReverseProxy.Configuration;

namespace ParityForge.Facade;

/// <summary>The latest route table, shared by the YARP configuration and the backend handler.</summary>
public sealed class RouteState
{
    private volatile RouteSnapshot current = RouteSnapshot.AllLegacy;

    public RouteSnapshot Current => current;

    public void Set(RouteSnapshot snapshot) => current = snapshot;
}

/// <summary>
/// YARP routes for the public API. Each public path is one route; its cluster is the module's
/// mode, and a path transform sends it to the matching backend on the internal listener.
/// </summary>
public static class ProxyConfig
{
    public const string InternalAddress = "http://127.0.0.1:8081";
    public static readonly string[] Modes = ["legacy", "shadow", "modern"];

    public static IReadOnlyList<ClusterConfig> Clusters() =>
        Modes.Select(mode => new ClusterConfig
        {
            ClusterId = mode,
            Destinations = new Dictionary<string, DestinationConfig> { ["internal"] = new() { Address = InternalAddress } },
        }).ToList();

    public static IReadOnlyList<RouteConfig> Routes(RouteSnapshot snapshot) =>
        Codecs.Programs.Select(pair =>
        {
            var mode = snapshot.For(pair.Value).Mode.ToLowerInvariant();
            if (!Modes.Contains(mode))
            {
                mode = "legacy";
            }
            return new RouteConfig
            {
                RouteId = pair.Value,
                ClusterId = mode,
                Match = new RouteMatch { Path = pair.Key, Methods = ["POST"] },
                Transforms = [new Dictionary<string, string> { ["PathSet"] = $"/backends/{mode}/{pair.Value}" }],
            };
        }).ToList();
}

/// <summary>Reads the route table every few seconds and reloads YARP when a mode changes.</summary>
public sealed class RouteRefresher(
    IRouteSource source,
    RouteState state,
    InMemoryConfigProvider proxy,
    FacadeOptions options,
    ILogger<RouteRefresher> logger) : BackgroundService
{
    public async Task RefreshOnceAsync(CancellationToken cancellationToken)
    {
        var snapshot = await source.FetchAsync(cancellationToken);
        if (snapshot.Version != state.Current.Version)
        {
            state.Set(snapshot);
            proxy.Update(ProxyConfig.Routes(snapshot), ProxyConfig.Clusters());
            logger.LogInformation("Routes updated to version {Version}", snapshot.Version);
        }
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await RefreshOnceAsync(stoppingToken);
            }
            catch (Exception exception) when (exception is not OperationCanceledException)
            {
                // Keep the last good table. With none yet, everything stays on legacy.
                logger.LogWarning("Route table refresh failed: {Type}", exception.GetType().Name);
            }
            await Task.Delay(TimeSpan.FromSeconds(Math.Max(1, options.RouteRefreshSeconds)), stoppingToken);
        }
    }
}
