namespace Offshoot.Generated;

/// <summary>
/// The record entry point: an LF-INPUT record (29 bytes) in, an LF-OUTPUT record
/// (37 bytes) out, exactly as BRCALL LATEFEE reads and writes them.
/// </summary>
public static class ModuleEntry
{
    public static string Process(string record)
    {
        var result = Assess(record);
        return result.Status
            + FixedWidth.Digits(result.DaysOverdue, 5, 0)
            + FixedWidth.Digits(result.Fee, 3, 2)
            + (result.Waived ? "Y" : "N")
            + FixedWidth.Digits(result.CreditUsed, 5, 2)
            + FixedWidth.Digits(result.CreditCarried, 5, 2)
            + FixedWidth.Digits(result.NetArrears, 7, 2);
    }

    private static LateFeeResult Assess(string record)
    {
        var balance = FixedWidth.Field(record, 0, 9);
        var due = FixedWidth.Field(record, 9, 6);
        var bill = FixedWidth.Field(record, 15, 6);
        var senior = FixedWidth.Field(record, 21, 1)[0] == 'Y';
        var credit = FixedWidth.Field(record, 22, 7);

        if (!FixedWidth.IsDigits(balance) || !FixedWidth.IsDigits(credit))
        {
            return LateFeeResult.Rejected("E10");
        }
        if (!FixedWidth.IsDigits(bill) || LateFeeCalculator.ExpandDate(FixedWidth.Integer(bill)) is not { } billDate)
        {
            return LateFeeResult.Rejected("E07");
        }
        if (!FixedWidth.IsDigits(due))
        {
            return LateFeeResult.Rejected("E07");
        }

        // A zero due date means nothing is overdue, and is valid.
        DateOnly? dueDate = null;
        var dueValue = FixedWidth.Integer(due);
        if (dueValue != 0)
        {
            dueDate = LateFeeCalculator.ExpandDate(dueValue);
            if (dueDate is null)
            {
                return LateFeeResult.Rejected("E07");
            }
        }

        return LateFeeCalculator.Assess(
            FixedWidth.ImpliedDecimal(balance, 2), dueDate, billDate, senior, FixedWidth.ImpliedDecimal(credit, 2));
    }
}
