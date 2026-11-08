// One input record per stdin line, one output record per stdout line. A record that
// throws produces a marker line instead, so one bad record cannot hide the others.
using System.Text;

using var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { NewLine = "\n" };
string? line;
while ((line = Console.In.ReadLine()) is not null)
{
    string result;
    try
    {
        result = Offshoot.Generated.ModuleEntry.Process(line);
    }
#pragma warning disable CA1031 // Any failure of generated code is reported as data.
    catch (Exception ex)
#pragma warning restore CA1031
    {
        result = "!EXCEPTION " + ex.GetType().Name;
    }
    output.WriteLine(result.Replace('\n', ' ').Replace('\r', ' '));
}
output.Flush();
