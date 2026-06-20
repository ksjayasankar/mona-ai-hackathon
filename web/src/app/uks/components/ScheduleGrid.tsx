import type { GapState } from "../api";

const CODE_STYLE: Record<string, string> = {
  D: "text-sky-700",
  N: "text-indigo-700",
  O: "text-slate-300",
};

export function ScheduleGrid({ preview }: { preview: GapState["schedule_preview"] | undefined }) {
  if (!preview?.rows?.length) return <p className="text-sm text-slate-400">No schedule loaded yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="text-slate-400">
            <th className="px-2 py-1 text-left font-medium">Staff</th>
            {preview.days.map((d) => (
              <th
                key={d}
                className={`px-1.5 py-1 text-center font-semibold ${d === preview.gap_day ? "text-[#b3122b]" : ""}`}
              >
                {d.replace(/^\w+ /, "")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((r) => (
            <tr key={r.employee_id} className={`border-t border-slate-100 ${r.is_winner ? "bg-emerald-50" : ""}`}>
              <td className="whitespace-nowrap px-2 py-1 font-medium text-slate-700">
                {r.is_winner ? "✅ " : ""}
                {r.name}
              </td>
              {preview.days.map((d) => {
                const code = r.grid[d] ?? "";
                const isGap = d === preview.gap_day;
                const flipped = r.is_winner && isGap;
                return (
                  <td
                    key={d}
                    className={`px-1.5 py-1 text-center font-semibold ${
                      flipped
                        ? "rounded bg-emerald-500 text-white"
                        : isGap
                          ? "bg-amber-50 " + (CODE_STYLE[code] ?? "text-slate-600")
                          : CODE_STYLE[code] ?? "text-slate-600"
                    }`}
                  >
                    {code}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
