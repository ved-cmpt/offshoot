using ParityForge.Generated;
using Xunit;

namespace ParityForge.Generated.Tests;

public sealed class StatementFormatterTests
{
    private const string Sage = "NG000001SAGE PEMBERTON                ";

    [Fact]
    public void A_regular_statement_line()
    {
        Assert.Equal(
            "E00NG000001 SAGE PEMBERTON       09/30/99   400      41.75  0.00   41.75           ",
            ModuleEntry.Process(Sage + "99093000400 000004175" + "00000" + "000000000" + "000004175"));
    }

    [Fact]
    public void The_total_due_box_keeps_four_whole_digits()
    {
        Assert.Equal("2345.67", StatementFormatter.Edited(12345.67m, 4, 2));
    }

    [Fact]
    public void Zero_prints_its_last_digit()
    {
        Assert.Equal("    0.00", StatementFormatter.Edited(0m, 5, 2));
    }

    [Fact]
    public void An_estimate_outranks_arrears()
    {
        var line = ModuleEntry.Process(Sage + "99022900400E000004175" + "00000" + "000000100" + "001234567");
        Assert.EndsWith("ESTIMATED ", line, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("990230")]
    [InlineData("991300")]
    [InlineData("99AB01")]
    public void Invalid_dates_are_rejected(string date)
    {
        Assert.StartsWith("E07", ModuleEntry.Process(Sage + date + "00400 000004175000000000000000000004175"), StringComparison.Ordinal);
    }

    [Fact]
    public void February_always_has_twenty_nine_days()
    {
        Assert.True(StatementFormatter.IsValidDate(2, 29));
        Assert.False(StatementFormatter.IsValidDate(2, 30));
    }
}
