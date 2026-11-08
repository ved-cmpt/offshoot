using Offshoot.Generated;
using Xunit;

namespace Offshoot.Generated.Tests;

public sealed class MeterReadValidatorTests
{
    [Fact]
    public void Usage_is_the_difference_between_reads()
    {
        Assert.Equal("E0000100N ", ModuleEntry.Process("+00100+00200A"));
    }

    [Fact]
    public void A_dial_rollover_counts_through_zero()
    {
        Assert.Equal("E0000150Y ", ModuleEntry.Process("+99950+00100A"));
    }

    [Fact]
    public void An_implausible_rollover_is_rejected()
    {
        Assert.Equal("E0400000N ", ModuleEntry.Process("+49999+00000A"));
    }

    [Fact]
    public void Estimated_reads_are_flagged()
    {
        Assert.Equal("E0000000NE", ModuleEntry.Process("+00100+00100E"));
    }

    [Theory]
    [InlineData(" 00100+00200A", "E01")]
    [InlineData("+00100-00001A", "E02")]
    [InlineData("+00100+00200X", "E03")]
    public void Invalid_reads_are_rejected_in_order(string record, string status)
    {
        Assert.Equal(status + "00000N ", ModuleEntry.Process(record));
    }

    [Fact]
    public void Minus_zero_is_not_negative()
    {
        var result = MeterReadValidator.Validate(0, 200, 'A');
        Assert.Equal("E00", result.Status);
        Assert.Equal(200, result.ConsumptionKwh);
    }
}
