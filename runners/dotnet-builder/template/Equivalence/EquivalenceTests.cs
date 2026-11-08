using System.Text.Json;
using Xunit;

namespace ParityForge.Equivalence.Tests;

/// <summary>Every recorded legacy case, replayed against the generated module.</summary>
public sealed class EquivalenceTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNameCaseInsensitive = true };

    private sealed record Case(string Input, string Expected);

    [Fact]
    public void Every_case_matches_the_legacy_output()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "cases.jsonl");
        var cases = File.ReadLines(path)
            .Where(line => line.Length > 0)
            .Select(line => JsonSerializer.Deserialize<Case>(line, Options)!)
            .ToList();
        Assert.NotEmpty(cases);
        foreach (var item in cases)
        {
            Assert.Equal(item.Expected, ParityForge.Generated.ModuleEntry.Process(item.Input));
        }
    }
}
