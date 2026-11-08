using System.Globalization;

namespace Offshoot.Generated;

/// <summary>One statement's values, field for field the SG-INPUT group.</summary>
public sealed record StatementInput(
    string CustomerId,
    string Name,
    int Year,
    int Month,
    int Day,
    int Kwh,
    char EstimateFlag,
    decimal CurrentCharge,
    decimal LateFee,
    decimal Arrears,
    decimal TotalDue);

/// <summary>Formats the 80-column statement print line (program STMTGEN).</summary>
public static class StatementFormatter
{
    // February always has 29 days here: the program does not know the year's century.
    private static readonly int[] MonthDays = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

    public static bool IsValidDate(int month, int day) =>
        month is >= 1 and <= 12 && day >= 1 && day <= MonthDays[month - 1];

    /// <summary>
    /// The columns match the pre-printed form. The amount boxes are narrower than the
    /// amounts, so high-order digits are dropped (ticket 96-233, kept on purpose), and the
    /// name is cut to 20 characters.
    /// </summary>
    public static string Format(StatementInput input)
    {
        var message = input.EstimateFlag == 'E' ? "ESTIMATED" : input.Arrears > 0m ? "PAST DUE" : string.Empty;
        return FixedWidth.Text(input.CustomerId, 8)
            + " " + FixedWidth.Text(input.Name, 20)
            + " " + Two(input.Month) + "/" + Two(input.Day) + "/" + Two(input.Year)
            + " " + Edited(input.Kwh, 5, 0)
            + " " + input.EstimateFlag
            + " " + Edited(input.CurrentCharge, 5, 2)
            + " " + Edited(input.LateFee, 2, 2)
            + " " + Edited(input.TotalDue, 4, 2)
            + " " + FixedWidth.Text(message, 10);
    }

    private static string Two(int value) => (value % 100).ToString("00", CultureInfo.InvariantCulture);

    /// <summary>
    /// A zero-suppressed edited picture such as ZZZZ9.99: integer digits that do not fit are
    /// dropped from the left, leading zeros print as spaces and the last integer digit always prints.
    /// </summary>
    public static string Edited(decimal value, int integerDigits, int scale)
    {
        var digits = FixedWidth.Digits(value, integerDigits, scale);
        var integerPart = digits[..integerDigits].TrimStart('0');
        integerPart = (integerPart.Length == 0 ? "0" : integerPart).PadLeft(integerDigits);
        return scale == 0 ? integerPart : integerPart + "." + digits[integerDigits..];
    }
}
