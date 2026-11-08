namespace ParityForge.Generated;

/// <summary>The tariff for one customer class (copybook RATES).</summary>
public sealed record Tariff(
    decimal Tier1Rate,
    decimal Tier2Rate,
    int BaseTierLimit,
    int SummerTierLimit,
    decimal ServiceCharge,
    decimal MinimumCharge)
{
    public static readonly Tariff Residential = new(0.0912m, 0.1185m, 600, 750, 4.25m, 8.50m);
    public static readonly Tariff Commercial = new(0.1040m, 0.0875m, 2000, 2500, 11.75m, 25.00m);
}

/// <summary>The priced period, field for field the RC-OUTPUT group.</summary>
public sealed record RateResult(
    string Status,
    int TierLimit,
    int Tier1Kwh,
    int Tier2Kwh,
    decimal Energy,
    decimal ServiceCharge,
    decimal Subtotal,
    bool MinimumApplied,
    decimal Levy,
    decimal Total)
{
    public static RateResult Rejected(string status) => new(status, 0, 0, 0, 0m, 0m, 0m, false, 0m, 0m);
}

/// <summary>Prices one billing period of usage (program RATECALC).</summary>
public static class RateCalculator
{
    public const decimal LevyRate = 0.0250m;
    public const int SummerFirstMonth = 6;
    public const int SummerLastMonth = 9;

    public static RateResult Calculate(char customerClass, int month, int kwh)
    {
        var tariff = customerClass == 'R' ? Tariff.Residential : Tariff.Commercial;
        var summer = month >= SummerFirstMonth && month <= SummerLastMonth;
        var limit = summer ? tariff.SummerTierLimit : tariff.BaseTierLimit;

        var tier1Kwh = kwh > limit ? limit : kwh;
        var tier2Kwh = kwh > limit ? kwh - limit : 0;

        // The tier amounts keep their four decimals until they are added, then round once.
        var energy = RoundToCent((tier1Kwh * tariff.Tier1Rate) + (tier2Kwh * tariff.Tier2Rate));

        var subtotal = energy + tariff.ServiceCharge;
        var minimumApplied = subtotal < tariff.MinimumCharge;
        if (minimumApplied)
        {
            subtotal = tariff.MinimumCharge;
        }

        var levy = RoundToCent(subtotal * LevyRate);
        return new RateResult(
            "E00", limit, tier1Kwh, tier2Kwh, energy, tariff.ServiceCharge, subtotal, minimumApplied, levy, subtotal + levy);
    }

    /// <summary>COMPUTE ... ROUNDED: round the amount to the cent.</summary>
    public static decimal RoundToCent(decimal amount) => Math.Round(amount, 2);
}
