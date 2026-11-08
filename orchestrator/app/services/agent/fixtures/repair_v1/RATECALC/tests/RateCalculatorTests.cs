using ParityForge.Generated;
using Xunit;

namespace ParityForge.Generated.Tests;

public sealed class RateCalculatorTests
{
    [Fact]
    public void Residential_usage_within_the_first_tier()
    {
        var result = RateCalculator.Calculate('R', 3, 400);
        Assert.Equal(600, result.TierLimit);
        Assert.Equal(36.48m, result.Energy);
        Assert.Equal(40.73m, result.Subtotal);
        Assert.Equal(1.02m, result.Levy);
        Assert.Equal(41.75m, result.Total);
    }

    [Fact]
    public void Summer_months_use_the_larger_first_tier()
    {
        var result = RateCalculator.Calculate('R', 7, 700);
        Assert.Equal(750, result.TierLimit);
        Assert.Equal(700, result.Tier1Kwh);
        Assert.Equal(0, result.Tier2Kwh);
        Assert.Equal(69.79m, result.Total);
    }

    [Fact]
    public void Commercial_usage_splits_across_both_tiers()
    {
        var result = RateCalculator.Calculate('C', 11, 3000);
        Assert.Equal(2000, result.Tier1Kwh);
        Assert.Equal(1000, result.Tier2Kwh);
        Assert.Equal(295.50m, result.Energy);
        Assert.Equal(314.93m, result.Total);
    }

    [Fact]
    public void A_small_bill_is_raised_to_the_minimum_before_the_levy()
    {
        var result = RateCalculator.Calculate('R', 1, 0);
        Assert.True(result.MinimumApplied);
        Assert.Equal(8.50m, result.Subtotal);
        Assert.Equal(8.71m, result.Total);
    }

    [Theory]
    [InlineData(610, 55.91)]
    [InlineData(630, 58.28)]
    public void Midpoints_round_half_up_like_cobol_rounded(int kwh, double energy)
    {
        Assert.Equal((decimal)energy, RateCalculator.Calculate('R', 10, kwh).Energy);
    }

    [Fact]
    public void The_levy_rounds_a_midpoint_up()
    {
        Assert.Equal(0.21m, RateCalculator.RoundToCent(0.205m));
    }

    [Theory]
    [InlineData("X0100100", "E05")]
    [InlineData("R1300100", "E06")]
    [InlineData("R0100 10", "E09")]
    public void Invalid_input_is_rejected_with_its_status(string record, string status)
    {
        Assert.StartsWith(status, ModuleEntry.Process(record), StringComparison.Ordinal);
        Assert.Equal(58, ModuleEntry.Process(record).Length);
    }

    [Fact]
    public void The_output_record_matches_the_legacy_layout()
    {
        Assert.Equal("E0000600004000000000000364800425000004073N0000102000004175", ModuleEntry.Process("R0300400"));
    }
}
