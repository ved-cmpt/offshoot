using System.Globalization;
using System.Text;
using System.Text.Json;

namespace Offshoot.Facade;

/// <summary>A request the facade refuses before any backend sees it.</summary>
public sealed class RequestError(string message) : Exception(message);

/// <summary>An output record that does not fit its layout.</summary>
public sealed class RecordError(string message) : Exception(message);

/// <summary>
/// The BillRite business API: JSON in and out, mapped to the fixed-width parameter blocks of
/// copy/CALLREC.cpy that both the legacy program and the generated module read and write.
/// Money travels as decimal strings, never as binary floats.
/// </summary>
public static class Codecs
{
    public static readonly IReadOnlyDictionary<string, string> Programs = new Dictionary<string, string>
    {
        ["/meter/validate"] = "MTRVAL",
        ["/billing/rate"] = "RATECALC",
        ["/billing/late-fee"] = "LATEFEE",
        ["/statement/render"] = "STMTGEN",
    };

    public static readonly IReadOnlyDictionary<string, int> OutputLengths = new Dictionary<string, int>
    {
        ["MTRVAL"] = 10,
        ["RATECALC"] = 58,
        ["LATEFEE"] = 37,
        ["STMTGEN"] = 83,
    };

    public static string Encode(string program, JsonElement body)
    {
        if (body.ValueKind != JsonValueKind.Object)
        {
            throw new RequestError("The request body must be a JSON object.");
        }
        return program switch
        {
            "MTRVAL" => Signed(body, "previous_read") + Signed(body, "current_read") + Text(body, "read_type", 1, exact: true),
            "RATECALC" => Text(body, "customer_class", 1, exact: true) + Whole(body, "month", 2) + Whole(body, "kwh", 5),
            "LATEFEE" => Money(body, "balance", 7) + Date(body, "due_date") + Date(body, "bill_date")
                + (Bool(body, "senior") ? "Y" : "N") + Money(body, "credit", 5),
            "STMTGEN" => Text(body, "customer_id", 8) + Text(body, "name", 30) + Date(body, "bill_date") + Whole(body, "kwh", 5)
                + Text(body, "estimate_flag", 1, exact: true) + Money(body, "current", 7) + Money(body, "fee", 3)
                + Money(body, "arrears", 7) + Money(body, "total_due", 7),
            _ => throw new RequestError("Unknown program."),
        };
    }

    public static Dictionary<string, object?> Decode(string program, string record)
    {
        if (!OutputLengths.TryGetValue(program, out var length) || record.Length != length)
        {
            throw new RecordError("The output record does not fit its layout.");
        }
        var reader = new Reader(record);
        var status = reader.Take(3);
        return program switch
        {
            "MTRVAL" => new()
            {
                ["status"] = status,
                ["consumption_kwh"] = reader.Int(5),
                ["rollover"] = reader.Take(1) == "Y",
                ["estimated"] = reader.Take(1) == "E",
            },
            "RATECALC" => new()
            {
                ["status"] = status,
                ["tier_limit"] = reader.Int(5),
                ["tier1_kwh"] = reader.Int(5),
                ["tier2_kwh"] = reader.Int(5),
                ["energy"] = reader.Money(9),
                ["service_charge"] = reader.Money(5),
                ["subtotal"] = reader.Money(9),
                ["minimum_applied"] = reader.Take(1) == "Y",
                ["levy"] = reader.Money(7),
                ["total"] = reader.Money(9),
            },
            "LATEFEE" => new()
            {
                ["status"] = status,
                ["days_overdue"] = reader.Int(5),
                ["fee"] = reader.Money(5),
                ["waived"] = reader.Take(1) == "Y",
                ["credit_used"] = reader.Money(7),
                ["credit_carried"] = reader.Money(7),
                ["net_arrears"] = reader.Money(9),
            },
            _ => new() { ["status"] = status, ["line"] = reader.Take(80) },
        };
    }

    private static JsonElement Field(JsonElement body, string name) =>
        body.TryGetProperty(name, out var value) ? value : throw new RequestError($"'{name}' is required.");

    private static int Number(JsonElement body, string name, int min, int max)
    {
        var value = Field(body, name);
        if (value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out var number) || number < min || number > max)
        {
            throw new RequestError($"'{name}' must be a whole number from {min} to {max}.");
        }
        return number;
    }

    private static string Whole(JsonElement body, string name, int digits) =>
        Number(body, name, 0, (int)Math.Pow(10, digits) - 1).ToString(CultureInfo.InvariantCulture).PadLeft(digits, '0');

    private static string Signed(JsonElement body, string name)
    {
        var number = Number(body, name, -99999, 99999);
        return (number < 0 ? "-" : "+") + Math.Abs(number).ToString(CultureInfo.InvariantCulture).PadLeft(5, '0');
    }

    private static string Text(JsonElement body, string name, int length, bool exact = false)
    {
        var value = Field(body, name);
        var text = value.ValueKind == JsonValueKind.String ? value.GetString()! : throw new RequestError($"'{name}' must be text.");
        if (text.Length > length || (exact && text.Length != length) || text.Any(c => c < ' ' || c > '~'))
        {
            throw new RequestError($"'{name}' must be {(exact ? "exactly" : "at most")} {length} printable characters.");
        }
        return text.PadRight(length);
    }

    private static bool Bool(JsonElement body, string name)
    {
        var value = Field(body, name);
        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new RequestError($"'{name}' must be true or false."),
        };
    }

    private static string Date(JsonElement body, string name)
    {
        var text = Text(body, name, 6, exact: true);
        return text.All(char.IsAsciiDigit) ? text : throw new RequestError($"'{name}' must be six digits, YYMMDD.");
    }

    private static string Money(JsonElement body, string name, int integerDigits)
    {
        var value = Field(body, name);
        var text = value.ValueKind == JsonValueKind.String ? value.GetString()! : throw new RequestError($"'{name}' must be a decimal string such as \"12.34\".");
        if (!decimal.TryParse(text, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var amount)
            || amount < 0 || decimal.Round(amount, 2) != amount || amount >= (decimal)Math.Pow(10, integerDigits))
        {
            throw new RequestError($"'{name}' must be a non-negative amount with at most two decimals and {integerDigits} whole digits.");
        }
        return ((long)(amount * 100)).ToString(CultureInfo.InvariantCulture).PadLeft(integerDigits + 2, '0');
    }

    private sealed class Reader(string record)
    {
        private int position;

        public string Take(int length)
        {
            var value = record.Substring(position, length);
            position += length;
            return value;
        }

        public int Int(int length)
        {
            var text = Take(length);
            return text.All(char.IsAsciiDigit) ? int.Parse(text, CultureInfo.InvariantCulture) : throw new RecordError("A numeric field is not numeric.");
        }

        public string Money(int length)
        {
            var text = Take(length);
            if (!text.All(char.IsAsciiDigit))
            {
                throw new RecordError("A numeric field is not numeric.");
            }
            var whole = text[..^2].TrimStart('0');
            return new StringBuilder(whole.Length == 0 ? "0" : whole).Append('.').Append(text[^2..]).ToString();
        }
    }
}
