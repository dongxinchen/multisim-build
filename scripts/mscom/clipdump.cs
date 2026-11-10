// clipdump — dump every clipboard format the way a 32-bit process sees it.
//
// Multisim is 32-bit and writes its own private clipboard formats for schematic
// fragments. A 64-bit process cannot read those (clipboard handles are not
// shared across bitness for private formats), so this must be built x86, and it
// must run on an STA thread to touch the clipboard at all.
//
// Build:  powershell -File build.ps1     (produces clipdump.exe)
// Usage:  clipdump.exe [outDir]          (defaults to %TEMP%\clipdump)
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

static class ClipDump
{
    [DllImport("user32.dll", SetLastError = true)] static extern bool OpenClipboard(IntPtr hWndNewOwner);
    [DllImport("user32.dll", SetLastError = true)] static extern bool CloseClipboard();
    [DllImport("user32.dll")] static extern uint EnumClipboardFormats(uint format);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClipboardFormatName(uint format, StringBuilder lpszFormatName, int cchMaxCount);
    [DllImport("user32.dll")] static extern IntPtr GetClipboardData(uint uFormat);
    [DllImport("kernel32.dll")] static extern IntPtr GlobalLock(IntPtr hMem);
    [DllImport("kernel32.dll")] static extern bool GlobalUnlock(IntPtr hMem);
    [DllImport("kernel32.dll")] static extern UIntPtr GlobalSize(IntPtr hMem);

    const int MAX_DUMP = 4 * 1024 * 1024;

    static string FormatName(uint f)
    {
        var sb = new StringBuilder(256);
        int n = GetClipboardFormatName(f, sb, sb.Capacity);
        if (n > 0) return sb.ToString();
        switch (f)
        {
            case 1: return "CF_TEXT";
            case 2: return "CF_BITMAP";
            case 3: return "CF_METAFILEPICT";
            case 8: return "CF_DIB";
            case 13: return "CF_UNICODETEXT";
            case 15: return "CF_HDROP";
            case 16: return "CF_LOCALE";
            case 17: return "CF_DIBV5";
            default: return "CF_" + f;
        }
    }

    [STAThread]
    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        string outDir = args.Length > 0 ? args[0] : Path.Combine(Path.GetTempPath(), "clipdump");
        Directory.CreateDirectory(outDir);

        if (!OpenClipboard(IntPtr.Zero))
        {
            Console.WriteLine("{\"ok\":false,\"error\":\"OpenClipboard failed: " + Marshal.GetLastWin32Error() + "\"}");
            return 2;
        }
        var lines = new List<string>();
        bool xmlFound = false;
        string xmlFormat = null;
        try
        {
            uint f = 0;
            int count = 0;
            while ((f = EnumClipboardFormats(f)) != 0)
            {
                count++;
                string name = FormatName(f);
                IntPtr h = GetClipboardData(f);
                if (h == IntPtr.Zero)
                {
                    lines.Add("{\"format\":" + Q(name) + ",\"id\":" + f + ",\"bytes\":0,\"note\":\"no handle\"}");
                    continue;
                }
                ulong size = GlobalSize(h).ToUInt64();
                IntPtr p = GlobalLock(h);
                byte[] buf = new byte[0];
                if (p != IntPtr.Zero && size > 0)
                {
                    int take = (int)Math.Min(size, (ulong)MAX_DUMP);
                    buf = new byte[take];
                    Marshal.Copy(p, buf, 0, take);
                    GlobalUnlock(h);
                }

                string safe = name.Replace('\\', '_').Replace('/', '_').Replace('*', '_').Replace('?', '_');
                string path = Path.Combine(outDir, string.Format("{0:D2}_{1}.bin", count, safe));
                File.WriteAllBytes(path, buf);

                // plain text formats -> also save as .txt for eyeballing
                string head = AsciiPreview(buf, 240);
                if (f == 1 || f == 13)
                {
                    Encoding enc = f == 13 ? Encoding.Unicode : Encoding.Default;
                    File.WriteAllText(Path.ChangeExtension(path, ".txt"), enc.GetString(buf), Encoding.UTF8);
                }

                bool hit = buf.Length > 0 && (Index(buf, "<?xml") >= 0 || Index(buf, "ElectronicsWorkbench") >= 0
                                              || Index(buf, "MSMCompressed") >= 0);
                if (hit && !xmlFound) { xmlFound = true; xmlFormat = name; }

                lines.Add("{\"format\":" + Q(name) + ",\"id\":" + f + ",\"bytes\":" + buf.Length +
                          ",\"xml\":" + (hit ? "true" : "false") + ",\"file\":" + Q(path) +
                          ",\"head\":" + Q(head) + "}");
            }
            Console.WriteLine("{\"ok\":true,\"formats\":" + count + ",\"xmlFound\":" + (xmlFound ? "true" : "false") +
                              (xmlFound ? ",\"xmlFormat\":" + Q(xmlFormat) : "") +
                              ",\"outDir\":" + Q(outDir) + ",\"items\":[" + string.Join(",", lines.ToArray()) + "]}");
            return xmlFound ? 0 : 1;
        }
        finally
        {
            CloseClipboard();
        }
    }

    static string AsciiPreview(byte[] b, int max)
    {
        var sb = new StringBuilder();
        int n = Math.Min(b.Length, max);
        for (int i = 0; i < n; i++)
        {
            byte c = b[i];
            sb.Append(c >= 0x20 && c < 0x7f ? (char)c : '.');
        }
        return sb.ToString();
    }

    static int Index(byte[] hay, string needle)
    {
        byte[] n = Encoding.ASCII.GetBytes(needle);
        for (int i = 0; i + n.Length <= hay.Length; i++)
        {
            bool ok = true;
            for (int j = 0; j < n.Length; j++) if (hay[i + j] != n[j]) { ok = false; break; }
            if (ok) return i;
        }
        return -1;
    }

    static string Q(string s)
    {
        if (s == null) return "null";
        var sb = new StringBuilder("\"");
        foreach (char c in s)
        {
            if (c == '"') sb.Append("\\\"");
            else if (c == '\\') sb.Append("\\\\");
            else if (c < 0x20 || c > 0x7e) sb.Append("\\u" + ((int)c).ToString("x4"));
            else sb.Append(c);
        }
        return sb.Append('"').ToString();
    }
}
