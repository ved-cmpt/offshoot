namespace LegacyLens.Placeholder;

/// <summary>
/// Placeholder until Run 03 adds the migrated services. It uses the rounding mode
/// COBOL's ROUNDED clause needs, so the toolchain proof exercises something real.
/// </summary>
public static class BuildProbe
{
    public static decimal RoundHalfUp(decimal value) =>
        Math.Round(value, 2, MidpointRounding.AwayFromZero);
}
