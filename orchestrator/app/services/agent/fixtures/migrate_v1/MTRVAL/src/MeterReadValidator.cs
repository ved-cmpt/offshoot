namespace ParityForge.Generated;

/// <summary>The validated read, field for field the MV-OUTPUT group.</summary>
public sealed record MeterReadResult(string Status, int ConsumptionKwh, bool Rollover, bool Estimated)
{
    public static MeterReadResult Rejected(string status) => new(status, 0, false, false);
}

/// <summary>Validates one meter read and works out the kWh used (program MTRVAL).</summary>
public static class MeterReadValidator
{
    public const int MeterMax = 99999;
    public const int MaxPlausibleUse = 50000;

    /// <summary>
    /// Checks apply in order and the first failure wins: both reads numeric (E01), neither
    /// negative (E02), read type A or E (E03). A current read below the previous one is a
    /// rollover unless the usage it implies is implausible (E04).
    /// </summary>
    public static MeterReadResult Validate(int? previous, int? current, char readType)
    {
        if (previous is null || current is null)
        {
            return MeterReadResult.Rejected("E01");
        }
        if (previous < 0 || current < 0)
        {
            return MeterReadResult.Rejected("E02");
        }
        if (readType is not ('A' or 'E'))
        {
            return MeterReadResult.Rejected("E03");
        }

        var estimated = readType == 'E';
        if (current >= previous)
        {
            return new MeterReadResult("E00", current.Value - previous.Value, false, estimated);
        }

        // The dials count up to 99999, one more tick to 00000, then on to the current read.
        var rolloverUse = (MeterMax - previous.Value) + 1 + current.Value;
        if (rolloverUse > MaxPlausibleUse)
        {
            return MeterReadResult.Rejected("E04");
        }
        return new MeterReadResult("E00", rolloverUse, true, estimated);
    }
}
