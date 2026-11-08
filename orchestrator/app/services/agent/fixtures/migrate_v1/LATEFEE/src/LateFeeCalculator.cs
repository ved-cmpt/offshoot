namespace ParityForge.Generated;

/// <summary>The assessed account, field for field the LF-OUTPUT group.</summary>
public sealed record LateFeeResult(
    string Status,
    int DaysOverdue,
    decimal Fee,
    bool Waived,
    decimal CreditUsed,
    decimal CreditCarried,
    decimal NetArrears)
{
    public static LateFeeResult Rejected(string status) => new(status, 0, 0m, false, 0m, 0m, 0m);
}

/// <summary>Late fees, the senior waiver and account credits (program LATEFEE).</summary>
public static class LateFeeCalculator
{
    public const int GraceDays = 30;
    public const decimal LateRate = 0.0150m;
    public const decimal MinimumFee = 2.00m;
    public const decimal MaximumFee = 50.00m;
    public const int CenturyPivot = 50;

    /// <summary>
    /// Expands a YYMMDD date with the fixed Y2K window: years at or above the pivot are
    /// 19YY, years below it are 20YY. Returns null when the result is not a real date.
    /// </summary>
    public static DateOnly? ExpandDate(int yymmdd)
    {
        var yy = yymmdd / 10000;
        var month = yymmdd / 100 % 100;
        var day = yymmdd % 100;
        var year = (yy >= CenturyPivot ? 1900 : 2000) + yy;
        if (month is < 1 or > 12 || day < 1 || day > DateTime.DaysInMonth(year, month))
        {
            return null;
        }
        return new DateOnly(year, month, day);
    }

    public static LateFeeResult Assess(decimal balance, DateOnly? dueDate, DateOnly billDate, bool senior, decimal credit)
    {
        var days = 0;
        if (balance > 0m && dueDate is not null)
        {
            var difference = billDate.DayNumber - dueDate.Value.DayNumber;
            if (difference > 0)
            {
                days = difference;
            }
        }

        var fee = 0m;
        var waived = false;
        if (days > GraceDays)
        {
            if (senior)
            {
                waived = true;
            }
            else
            {
                // Round first, then hold the fee between the minimum and the maximum.
                fee = Math.Round(balance * LateRate, 2, MidpointRounding.AwayFromZero);
                fee = Math.Clamp(fee, MinimumFee, MaximumFee);
            }
        }

        // Credit offsets the balance and the fee only. What is left of it is carried.
        var grossArrears = balance + fee;
        var creditUsed = credit >= grossArrears ? grossArrears : credit;
        return new LateFeeResult("E00", days, fee, waived, creditUsed, credit - creditUsed, grossArrears - creditUsed);
    }
}
