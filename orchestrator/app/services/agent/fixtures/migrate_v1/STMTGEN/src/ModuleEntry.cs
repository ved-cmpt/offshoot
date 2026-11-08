namespace Offshoot.Generated;

/// <summary>
/// The record entry point: an SG-INPUT record (82 bytes) in, an SG-OUTPUT record
/// (83 bytes) out, exactly as BRCALL STMTGEN reads and writes them.
/// </summary>
public static class ModuleEntry
{
    private static readonly string BlankLine = new(' ', 80);

    public static string Process(string record)
    {
        var date = FixedWidth.Field(record, 38, 6);
        if (!FixedWidth.IsDigits(date))
        {
            return "E07" + BlankLine;
        }
        var year = FixedWidth.Integer(date[..2]);
        var month = FixedWidth.Integer(date[2..4]);
        var day = FixedWidth.Integer(date[4..]);
        if (!StatementFormatter.IsValidDate(month, day))
        {
            return "E07" + BlankLine;
        }

        var kwh = FixedWidth.Field(record, 44, 5);
        var current = FixedWidth.Field(record, 50, 9);
        var fee = FixedWidth.Field(record, 59, 5);
        var arrears = FixedWidth.Field(record, 64, 9);
        var total = FixedWidth.Field(record, 73, 9);
        if (!FixedWidth.IsDigits(kwh) || !FixedWidth.IsDigits(current) || !FixedWidth.IsDigits(fee)
            || !FixedWidth.IsDigits(arrears) || !FixedWidth.IsDigits(total))
        {
            return "E10" + BlankLine;
        }

        var input = new StatementInput(
            FixedWidth.Field(record, 0, 8),
            FixedWidth.Field(record, 8, 30),
            year,
            month,
            day,
            FixedWidth.Integer(kwh),
            FixedWidth.Field(record, 49, 1)[0],
            FixedWidth.ImpliedDecimal(current, 2),
            FixedWidth.ImpliedDecimal(fee, 2),
            FixedWidth.ImpliedDecimal(arrears, 2),
            FixedWidth.ImpliedDecimal(total, 2));
        return "E00" + StatementFormatter.Format(input);
    }
}
