namespace Offshoot.Generated;

/// <summary>
/// The record entry point: an RC-INPUT record (8 bytes) in, an RC-OUTPUT record
/// (58 bytes) out, exactly as BRCALL RATECALC reads and writes them.
/// </summary>
public static class ModuleEntry
{
    public static string Process(string record)
    {
        var result = Price(record);
        return result.Status
            + FixedWidth.Digits(result.TierLimit, 5, 0)
            + FixedWidth.Digits(result.Tier1Kwh, 5, 0)
            + FixedWidth.Digits(result.Tier2Kwh, 5, 0)
            + FixedWidth.Digits(result.Energy, 7, 2)
            + FixedWidth.Digits(result.ServiceCharge, 3, 2)
            + FixedWidth.Digits(result.Subtotal, 7, 2)
            + (result.MinimumApplied ? "Y" : "N")
            + FixedWidth.Digits(result.Levy, 5, 2)
            + FixedWidth.Digits(result.Total, 7, 2);
    }

    private static RateResult Price(string record)
    {
        var customerClass = FixedWidth.Field(record, 0, 1)[0];
        var month = FixedWidth.Field(record, 1, 2);
        var kwh = FixedWidth.Field(record, 3, 5);

        if (customerClass is not ('R' or 'C'))
        {
            return RateResult.Rejected("E05");
        }
        if (!FixedWidth.IsDigits(month) || FixedWidth.Integer(month) is < 1 or > 12)
        {
            return RateResult.Rejected("E06");
        }
        if (!FixedWidth.IsDigits(kwh))
        {
            return RateResult.Rejected("E09");
        }
        return RateCalculator.Calculate(customerClass, FixedWidth.Integer(month), FixedWidth.Integer(kwh));
    }
}
