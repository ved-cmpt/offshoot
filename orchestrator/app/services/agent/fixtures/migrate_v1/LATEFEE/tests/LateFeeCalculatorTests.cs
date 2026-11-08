using ParityForge.Generated;
using Xunit;

namespace ParityForge.Generated.Tests;

public sealed class LateFeeCalculatorTests
{
    [Fact]
    public void More_than_thirty_days_overdue_earns_a_fee()
    {
        Assert.Equal("E000003100300N00000000000000000020300", ModuleEntry.Process("000020000990101990201N0000000"));
    }

    [Fact]
    public void Exactly_thirty_days_is_still_within_grace()
    {
        var result = LateFeeCalculator.Assess(200m, new DateOnly(1999, 1, 1), new DateOnly(1999, 1, 31), false, 0m);
        Assert.Equal(30, result.DaysOverdue);
        Assert.Equal(0m, result.Fee);
    }

    [Fact]
    public void Seniors_have_the_fee_waived()
    {
        Assert.Equal("E000003100000Y00000000000000000020000", ModuleEntry.Process("000020000990101990201Y0000000"));
    }

    [Theory]
    [InlineData(10.00, 2.00)]
    [InlineData(200.00, 3.00)]
    [InlineData(9000.00, 50.00)]
    public void The_fee_is_held_between_the_minimum_and_the_maximum(double balance, double fee)
    {
        var result = LateFeeCalculator.Assess((decimal)balance, new DateOnly(1999, 1, 1), new DateOnly(1999, 3, 1), false, 0m);
        Assert.Equal((decimal)fee, result.Fee);
    }

    [Theory]
    [InlineData(490101, 2049)]
    [InlineData(500101, 1950)]
    public void Two_digit_years_use_the_century_window(int yymmdd, int year)
    {
        Assert.Equal(year, LateFeeCalculator.ExpandDate(yymmdd)!.Value.Year);
    }

    [Fact]
    public void Credit_offsets_the_arrears_and_the_rest_is_carried()
    {
        var result = LateFeeCalculator.Assess(100m, null, new DateOnly(1999, 9, 30), false, 150m);
        Assert.Equal(100m, result.CreditUsed);
        Assert.Equal(50m, result.CreditCarried);
        Assert.Equal(0m, result.NetArrears);
    }

    [Theory]
    [InlineData("00002000 990101990201N0000000", "E10")]
    [InlineData("000020000990101990229N0000000", "E07")]
    [InlineData("000020000000100990201N0000000", "E07")]
    public void Invalid_input_is_rejected(string record, string status)
    {
        Assert.Equal(status + "0000000000N00000000000000000000000", ModuleEntry.Process(record));
    }
}
