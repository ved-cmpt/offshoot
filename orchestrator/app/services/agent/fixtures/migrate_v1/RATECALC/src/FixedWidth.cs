using System.Globalization;

namespace ParityForge.Generated;

/// <summary>Reads and writes the fixed-width records of the CALLREC parameter blocks.</summary>
internal static class FixedWidth
{
    /// <summary>A field by offset and length. A short record is padded with spaces, as the COBOL MOVE does.</summary>
    public static string Field(string record, int offset, int length)
    {
        var padded = record.Length >= offset + length ? record : record.PadRight(offset + length);
        return padded.Substring(offset, length);
    }

    /// <summary>The COBOL NUMERIC class test for an unsigned DISPLAY field: digits only.</summary>
    public static bool IsDigits(string text)
    {
        if (text.Length == 0)
        {
            return false;
        }
        foreach (var c in text)
        {
            if (c is < '0' or > '9')
            {
                return false;
            }
        }
        return true;
    }

    /// <summary>An implied-decimal field as a decimal. Only call this on a field that passed IsDigits.</summary>
    public static decimal ImpliedDecimal(string digits, int scale) =>
        decimal.Parse(digits, NumberStyles.None, CultureInfo.InvariantCulture) / Scale(scale);

    public static int Integer(string digits) => int.Parse(digits, NumberStyles.None, CultureInfo.InvariantCulture);

    /// <summary>
    /// An unsigned implied-decimal field. Like a COBOL MOVE, digits beyond the field's
    /// integer positions are dropped from the left and extra decimals are truncated.
    /// </summary>
    public static string Digits(decimal value, int integerDigits, int scale)
    {
        var scaled = decimal.Truncate(Math.Abs(value) * Scale(scale));
        scaled %= Scale(integerDigits + scale);
        return scaled.ToString("0", CultureInfo.InvariantCulture).PadLeft(integerDigits + scale, '0');
    }

    public static string Text(string value, int length) =>
        value.Length >= length ? value[..length] : value.PadRight(length);

    private static decimal Scale(int places)
    {
        var result = 1m;
        for (var i = 0; i < places; i++)
        {
            result *= 10m;
        }
        return result;
    }
}
