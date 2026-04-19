import { BarChart, GraphChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent } from 'echarts/components'
import { init, use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

use([
  GraphChart,
  LineChart,
  BarChart,
  GridComponent,
  LegendComponent,
  CanvasRenderer,
])

export const echarts = {
  init,
}
