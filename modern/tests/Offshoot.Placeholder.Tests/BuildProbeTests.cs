using Offshoot.Placeholder;
using Xunit;

namespace Offshoot.Placeholder.Tests;

public class BuildProbeTests
{
    [Theory]
    [InlineData("55.905", "55.91")]
    [InlineData("55.904", "55.90")]
    [InlineData("58.275", "58.28")]
    public void RoundHalfUp_rounds_midpoints_away_from_zero(string input, string expected)
    {
        Assert.Equal(decimal.Parse(expected), BuildProbe.RoundHalfUp(decimal.Parse(input)));
    }
}
