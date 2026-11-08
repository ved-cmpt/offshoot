using System.Text.Json;

namespace Offshoot.Facade;

public sealed record BackendResult(int Status, object Body, string Route);

/// <summary>
/// The three backends behind the YARP routes. Legacy calls the COBOL program, modern calls the
/// approved artifact, and shadow calls both, reports the comparison, and answers with legacy.
/// </summary>
public sealed class BackendHandler(
    ILegacyBackend legacy,
    IModernBackend modern,
    IShadowReporter reporter,
    RouteState routes,
    ILogger<BackendHandler> logger)
{
    public async Task<BackendResult> HandleAsync(string mode, string program, JsonElement body, CancellationToken cancellationToken)
    {
        if (!Codecs.OutputLengths.ContainsKey(program))
        {
            return Error(404, "NOT_FOUND", "Unknown program.", mode);
        }
        string record;
        try
        {
            record = Codecs.Encode(program, body);
        }
        catch (RequestError error)
        {
            return Error(422, "VALIDATION_ERROR", error.Message, mode);
        }

        try
        {
            switch (mode)
            {
                case "legacy":
                    return Answer(program, await legacy.CallAsync(program, record, cancellationToken), "legacy");
                case "modern":
                {
                    var artifact = routes.Current.For(program).Artifact;
                    if (artifact is null)
                    {
                        return Error(503, "NO_APPROVED_ARTIFACT", "No approved artifact is routed for this module.", mode);
                    }
                    return Answer(program, await modern.CallAsync(program, record, artifact, cancellationToken), "modern");
                }
                case "shadow":
                    return await ShadowAsync(program, record, cancellationToken);
                default:
                    return Error(404, "NOT_FOUND", "Unknown route.", mode);
            }
        }
        catch (BackendException error)
        {
            return Error(502, error.Code, "A backend did not answer.", mode);
        }
        catch (RecordError)
        {
            return Error(502, "BAD_RECORD", "A backend answered with a record that does not fit its layout.", mode);
        }
    }

    private async Task<BackendResult> ShadowAsync(string program, string record, CancellationToken cancellationToken)
    {
        var legacyRecord = await legacy.CallAsync(program, record, cancellationToken);
        var artifact = routes.Current.For(program).Artifact;
        string modernRecord;
        try
        {
            modernRecord = artifact is null
                ? "!NO_ARTIFACT"
                : await modern.CallAsync(program, record, artifact, cancellationToken);
        }
        catch (BackendException error)
        {
            // The modern side failing is a difference to record, not a reason to fail the caller.
            modernRecord = "!" + error.Code;
        }
        try
        {
            await reporter.ReportAsync(program, record, legacyRecord, modernRecord, cancellationToken);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            logger.LogWarning("Shadow report failed: {Type}", exception.GetType().Name);
        }
        return Answer(program, legacyRecord, "shadow");
    }

    private static BackendResult Answer(string program, string record, string route) =>
        new(200, Codecs.Decode(program, record), route);

    private static BackendResult Error(int status, string code, string message, string route) =>
        new(status, new { error = new { code, message } }, route);
}
