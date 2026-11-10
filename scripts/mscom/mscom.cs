// mscom — drive Multisim through its COM interface (MSInterface.dll).
//
// Why C# instead of PowerShell: PowerShell's dynamic COM call sites crash with
// AccessViolationException inside VariantClear on this interface, and the
// component is 32-bit only — this must be built as x86 and run by a 32-bit
// host. Both facts are measured, see references/mscom.md.
//
// Build:  powershell -File build.ps1      (needs .NET Framework 4.x csc.exe)
//
// Commands
//   mscom probe                 app version / connection state
//   mscom dump   <circuit.ms14> components, their RLC values, and the pin->net table
//   mscom diag   <circuit.ms14> what the simulation APIs expose (diagnostics)
//   mscom saveas <circuit.ms14> <out.ms14>
//
// Every command prints one JSON object on stdout. Exit codes: 0 ok, 2 usage,
// 3 cannot reach Multisim, 4 no circuit, 5 save failed.
//
// Deliberately absent: DC/AC/transient data collection. EnumOutputs returns
// nothing for a circuit without probes, and SetOutputRequest/DoDCOperatingPoint/
// DoACSweep all come back E_FAIL there, so simulation data cannot be fetched
// this way. Use F5 in the GUI, or compute the check in Python.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

static class MsCom
{
    const string PROGID = "MultisimInterface.MultisimApp.1";

    static object app;
    static object circ;

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        string cmd = args.Length > 0 ? args[0].ToLowerInvariant() : "probe";
        try
        {
            if (cmd == "probe")
            {
                Attach(null);
                return Probe();
            }
            if (args.Length < 2)
            {
                Err("usage: mscom <probe|dump|diag|saveas> <circuit.ms14> [...]");
                return 2;
            }
            Attach(args[1]);
            switch (cmd)
            {
                case "dump": return Dump();
                case "diag": return Diag();
                case "saveas":
                    if (args.Length < 3) { Err("usage: mscom saveas <circuit.ms14> <out.ms14>"); return 2; }
                    return SaveAs(args[2]);
                default:
                    Err("unknown command '" + cmd + "'; use probe|dump|diag|saveas");
                    return 2;
            }
        }
        catch (Exception e)
        {
            Err((e.InnerException ?? e).Message);
            return 3;
        }
        finally
        {
            try { if (app != null) Call(app, "Disconnect"); } catch { }
        }
    }

    // ---- COM plumbing -----------------------------------------------------

    static object Get(object o, string name)
    {
        return o.GetType().InvokeMember(name, BindingFlags.GetProperty, null, o, null);
    }

    static object Get(object o, string name, object[] args)
    {
        return o.GetType().InvokeMember(name, BindingFlags.GetProperty, null, o, args);
    }

    static object Call(object o, string name, params object[] args)
    {
        return o.GetType().InvokeMember(name, BindingFlags.InvokeMethod, null, o, args);
    }

    // IMultisimApp has no "current circuit" accessor, so a circuit is always
    // addressed by its file: OpenFile returns the live object for it.
    static void Attach(string ms14)
    {
        Type t = Type.GetTypeFromProgID(PROGID);
        if (t == null) throw new Exception("ProgID " + PROGID + " is not registered; is Multisim installed?");
        app = Activator.CreateInstance(t);
        Call(app, "Connect");
        if (!(bool)Get(app, "IsConnected"))
            throw new Exception("Connect() failed: " + Str(Get(app, "LastErrorMessage")) +
                                "  (start Multisim first)");
        if (string.IsNullOrEmpty(ms14)) { circ = null; return; }
        circ = Call(app, "OpenFile", ms14);
        if (circ == null) throw new Exception("OpenFile returned no circuit for " + ms14);
    }

    static string Str(object o) { return o == null ? "" : o.ToString(); }

    static void Err(string msg)
    {
        Console.Out.WriteLine("{\"ok\":false,\"error\":" + J(msg) + "}");
        Console.Out.Flush();
    }

    static string J(string s)
    {
        if (s == null) return "null";
        var sb = new StringBuilder("\"");
        foreach (char c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20 || c > 0x7e) sb.Append("\\u" + ((int)c).ToString("x4"));
                    else sb.Append(c);
                    break;
            }
        }
        return sb.Append('"').ToString();
    }

    // ---- commands ---------------------------------------------------------

    static int Probe()
    {
        var sb = new StringBuilder("{\"ok\":true");
        sb.Append(",\"progid\":").Append(J(PROGID));
        sb.Append(",\"version\":").Append(J(Str(Get(app, "VersionInfo"))));
        sb.Append(",\"appPath\":").Append(J(Str(Get(app, "Path"))));
        sb.Append(",\"connected\":").Append((bool)Get(app, "IsConnected") ? "true" : "false");
        sb.Append('}');
        Console.Out.WriteLine(sb.ToString());
        return 0;
    }

    static int Dump()
    {
        string name = Str(Get(circ, "CircuitName"));
        string file = Str(Get(circ, "FileName"));

        var refs = new List<string>();
        try
        {
            object e0 = Call(circ, "EnumComponents", 0);   // ComponentAll
            if (e0 is IEnumerable) foreach (object o in (IEnumerable)e0) if (o != null) refs.Add(o.ToString());
        }
        catch (Exception e) { Console.Error.WriteLine("EnumComponents: " + (e.InnerException ?? e).Message); }

        var sb = new StringBuilder();
        sb.Append("{\"ok\":true,\"circuit\":").Append(J(name));
        sb.Append(",\"file\":").Append(J(file));

        // RLCValue is a get/put property taking the ref; sources have no RLC value
        sb.Append(",\"components\":[");
        for (int i = 0; i < refs.Count; i++)
        {
            if (i > 0) sb.Append(',');
            string v = null;
            try
            {
                object o = Get(circ, "RLCValue", new object[] { refs[i] });
                if (o != null) v = Convert.ToString(o, CultureInfo.InvariantCulture);
            }
            catch { }
            sb.Append("{\"ref\":").Append(J(refs[i])).Append(",\"rlc\":").Append(v == null ? "null" : J(v)).Append('}');
        }
        sb.Append("],\"nets\":{");

        string tmp = Path.Combine(Path.GetTempPath(), "mscom_netlist_" + Guid.NewGuid().ToString("N") + ".txt");
        bool wrote = TryNetlist(tmp);
        var nets = new SortedDictionary<string, List<string>>();
        if (wrote)
        {
            foreach (string line in File.ReadAllLines(tmp, Encoding.GetEncoding(936)))
            {
                if (line.Trim().Length == 0 || line.StartsWith("-")) continue;
                string[] f = Regex.Split(line.Trim(), @"\s{2,}");
                if (f.Length < 4) continue;
                string net = f[0].Trim();
                string refer = f[2].Trim();
                string pin = f[3].Trim();
                if (net.Length == 0 || !Regex.IsMatch(net, @"^[A-Za-z0-9_.\-+]+$")) continue;
                if (!refs.Contains(refer)) continue;
                List<string> list;
                if (!nets.TryGetValue(net, out list)) { list = new List<string>(); nets[net] = list; }
                list.Add(refer + ":" + pin);
            }
            try { File.Delete(tmp); } catch { }
        }

        bool firstNet = true;
        foreach (KeyValuePair<string, List<string>> kv in nets)
        {
            if (!firstNet) sb.Append(',');
            firstNet = false;
            sb.Append(J(kv.Key)).Append(":[");
            for (int i = 0; i < kv.Value.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(J(kv.Value[i]));
            }
            sb.Append(']');
        }
        sb.Append("},\"netlistOk\":").Append(wrote ? "true" : "false").Append('}');
        Console.Out.WriteLine(sb.ToString());
        return 0;
    }

    // ReportNetlist returns E_ACCESSDENIED on this build even when the file is
    // written, so success is decided by the file, not by the HRESULT.
    static bool TryNetlist(string path)
    {
        try { Call(circ, "ReportNetlist", false, 0 /* ExportText */, path); } catch { }
        return File.Exists(path) && new FileInfo(path).Length > 0;
    }

    // Explains why simulation data is unavailable: a circuit without probes
    // exposes no simulation outputs at all.
    static int Diag()
    {
        var labels = new[] { "All", "Voltage", "Current", "Power", "Digital" };
        var sb = new StringBuilder("{\"ok\":true,\"outputsByFilter\":{");
        for (int f = 0; f < labels.Length; f++)
        {
            if (f > 0) sb.Append(',');
            var items = new List<string>();
            try
            {
                object eo = Call(circ, "EnumOutputs", f);
                if (eo is IEnumerable) foreach (object o in (IEnumerable)eo) if (o != null) items.Add(o.ToString());
            }
            catch (Exception e) { Console.Error.WriteLine("EnumOutputs(" + f + "): " + (e.InnerException ?? e).Message); }
            sb.Append(J(labels[f])).Append(":[").Append(string.Join(",", QuoteAll(items).ToArray())).Append(']');
        }
        sb.Append("},\"inputs\":[");
        var ins = new List<string>();
        try
        {
            object ei = Call(circ, "EnumInputs", 0);
            if (ei is IEnumerable) foreach (object o in (IEnumerable)ei) if (o != null) ins.Add(o.ToString());
        }
        catch (Exception e) { Console.Error.WriteLine("EnumInputs: " + (e.InnerException ?? e).Message); }
        sb.Append(string.Join(",", QuoteAll(ins).ToArray())).Append("]}");
        Console.Out.WriteLine(sb.ToString());
        return 0;
    }

    static List<string> QuoteAll(List<string> xs)
    {
        var outp = new List<string>();
        foreach (string x in xs) outp.Add(J(x));
        return outp;
    }

    static int SaveAs(string path)
    {
        Call(circ, "SaveAs", path);
        bool ok = File.Exists(path) && new FileInfo(path).Length > 0;
        Console.Out.WriteLine("{\"ok\":" + (ok ? "true" : "false") + ",\"path\":" + J(path) +
                              ",\"bytes\":" + (ok ? new FileInfo(path).Length.ToString() : "0") + "}");
        return ok ? 0 : 5;
    }
}
