namespace Offshoot.Generated;

/// <summary>
/// The record entry point: an MV-INPUT record (13 bytes) in, an MV-OUTPUT record
/// (10 bytes) out, exactly as BRCALL MTRVAL reads and writes them.
/// </summary>
public static class ModuleEntry
{
    public static string Process(string record)
    {
        var previous = SignedRead(FixedWidth.Field(record, 0, 6));
        var current = SignedRead(FixedWidth.Field(record, 6, 6));
        var readType = FixedWidth.Field(record, 12, 1)[0];

        var result = MeterReadValidator.Validate(previous, current, readType);
        return result.Status
            + FixedWidth.Digits(result.ConsumptionKwh, 5, 0)
            + (result.Rollover ? "Y" : "N")
            + (result.Estimated ? "E" : " ");
    }

    /// <summary>
    /// PIC S9(5) SIGN IS LEADING SEPARATE: a '+' or '-' and five digits. Anything else is
    /// not numeric. Minus zero is zero, so it is not negative.
    /// </summary>
    private static int? SignedRead(string field)
    {
        var digits = field[1..];
        if (field[0] is not ('+' or '-') || !FixedWidth.IsDigits(digits))
        {
            return null;
        }
        var value = FixedWidth.Integer(digits);
        return field[0] == '-' ? -value : value;
    }
}
