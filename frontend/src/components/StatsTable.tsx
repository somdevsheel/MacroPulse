import { fmtNum, fmtPct, fmtShare, signClass, WINDOW_LABELS, WINDOW_ORDER } from '../services/format'
import type { WindowStats } from '../types'

export function StatsTable({ stats, neutralPct }: { stats: WindowStats[]; neutralPct: number }) {
  const rows = [...stats].sort((a, b) => WINDOW_ORDER.indexOf(a.window) -
                                         WINDOW_ORDER.indexOf(b.window))
  return (
    <table>
      <thead>
        <tr>
          <th>Window</th><th className="text-right">n</th><th className="text-right">Mean</th>
          <th className="text-right">Median</th><th className="text-right">Bull</th>
          <th className="text-right">Bear</th><th className="text-right">Neutral</th>
          <th className="text-right" title="initial +5m move reversed at this horizon">Reversal</th>
          <th className="text-right" title="median realized-vol ratio post/pre (same length)">Vol ×</th>
          <th className="text-right">Max +</th><th className="text-right">Max −</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(s => (
          <tr key={s.window} className={s.window.startsWith('pre') ? 'text-muted' : ''}>
            <td>{WINDOW_LABELS[s.window] ?? s.window}</td>
            <td className="text-right">{s.n}</td>
            <td className={`text-right ${signClass(s.mean_pct)}`}>{fmtPct(s.mean_pct)}</td>
            <td className={`text-right ${signClass(s.median_pct)}`}>{fmtPct(s.median_pct)}</td>
            <td className="text-right text-up">{fmtShare(s.pct_bullish)}</td>
            <td className="text-right text-down">{fmtShare(s.pct_bearish)}</td>
            <td className="text-right">{fmtShare(s.pct_neutral)}</td>
            <td className="text-right" title={`${s.reversal_n} events with a clear +5m move`}>
              {fmtShare(s.reversal_frequency)}</td>
            <td className="text-right">{s.avg_vol_ratio ? `${fmtNum(s.avg_vol_ratio, 1)}×` : '—'}</td>
            <td className="text-right text-up">{fmtPct(s.max_positive_pct, 2)}</td>
            <td className="text-right text-down">{fmtPct(s.max_negative_pct, 2)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr><td colSpan={11} className="text-muted text-[11px] whitespace-normal">
          Returns from the last price before release. Bull/bear = beyond ±{neutralPct}%.
          Reversal = clear +5m move whose sign flipped by that horizon. Vol × = median of
          post/pre realized-volatility ratios.
        </td></tr>
      </tfoot>
    </table>
  )
}
