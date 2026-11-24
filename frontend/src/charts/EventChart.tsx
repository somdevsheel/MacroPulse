import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineStyle,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  type WhitespaceData,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import type { BarsResponse } from '../types'

interface Props {
  data: BarsResponse
  precision: number
  height?: number
}

/** 1-minute candles around a release. Missing minutes are inserted as whitespace so gaps stay
 *  visible on the time axis instead of being compressed away. Times are UTC. */
export function EventChart({ data, precision, height = 380 }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, {
      height,
      layout: { background: { type: ColorType.Solid, color: '#11161e' }, textColor: '#7d8899',
                fontFamily: 'ui-monospace, monospace', fontSize: 11 },
      grid: { vertLines: { color: '#1a212b' }, horzLines: { color: '#1a212b' } },
      rightPriceScale: { borderColor: '#1f2733' },
      timeScale: { borderColor: '#1f2733', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      autoSize: true,
    })
    seriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    })
    chartRef.current = chart
    return () => { chart.remove(); chartRef.current = null; seriesRef.current = null }
  }, [height])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!series || !chart) return
    series.applyOptions({ priceFormat: { type: 'price', precision, minMove: 10 ** -precision } })

    const byTime = new Map(data.bars.map(b => [b.time, b]))
    const points: (CandlestickData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] = []
    if (data.bars.length) {
      const first = data.bars[0].time
      const last = data.bars[data.bars.length - 1].time
      for (let t = first; t <= last; t += 60) {
        const b = byTime.get(t)
        points.push(b ? { time: t as UTCTimestamp, open: b.open, high: b.high, low: b.low,
                          close: b.close }
                      : { time: t as UTCTimestamp })
      }
    }
    series.setData(points)

    // Release marker on the first bar at/after the release instant.
    const rel = data.bars.find(b => b.time >= data.release_epoch)
    const markers = createSeriesMarkers(series, rel ? [{
      time: rel.time as UTCTimestamp, position: 'aboveBar', color: '#f0b429', shape: 'arrowDown',
      text: 'release',
    }] : [])
    // Last price before release = reaction anchor.
    const before = [...data.bars].reverse().find(b => b.time < data.release_epoch)
    const line = before ? series.createPriceLine({
      price: before.close, color: '#f0b429', lineStyle: LineStyle.Dashed, lineWidth: 1,
      axisLabelVisible: true, title: 'pre-release',
    }) : null
    chart.timeScale().fitContent()
    return () => { markers.detach(); if (line) series.removePriceLine(line) }
  }, [data, precision])

  return <div ref={ref} className="w-full" style={{ height }} />
}
