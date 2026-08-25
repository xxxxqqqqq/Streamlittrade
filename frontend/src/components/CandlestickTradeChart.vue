<script setup lang="ts">
import {computed,ref,watch} from 'vue'

const props=defineProps<{bars:any[];signals:any[];events:any[]}>()
const emit=defineEmits<{select:[value:any]}>()

const width=1000,padding=46,priceTop=20,priceBottom=318,volumeTop=336,volumeBottom=398,scoreTop=426,scoreBottom=492,navigatorTop=518,navigatorBottom=542,chartHeight=565,minWindow=20
const windowSize=ref(160),windowStart=ref(0),preset=ref(160),drag=ref<{x:number;start:number;active:boolean}|null>(null)
const visible=computed(()=>props.bars.slice(windowStart.value,windowStart.value+windowSize.value))
const signalMap=computed(()=>new Map(props.signals.map(item=>[item.date,item])))
const eventMap=computed(()=>{const map=new Map<string,any[]>();for(const item of props.events){const rows=map.get(item.date)||[];rows.push(item);map.set(item.date,rows)}return map})
const prices=computed(()=>visible.value.flatMap(item=>[Number(item.low),Number(item.high)]).filter(Number.isFinite))
const minPrice=computed(()=>Math.min(...prices.value)),maxPrice=computed(()=>Math.max(...prices.value))
const maxVolume=computed(()=>Math.max(1,...visible.value.map(item=>Number(item.volume)||0)))
const x=(index:number)=>padding+index*(width-padding*2)/Math.max(visible.value.length-1,1)
const py=(value:number)=>priceBottom-(value-minPrice.value)/(maxPrice.value-minPrice.value||1)*(priceBottom-priceTop)
const vy=(value:number)=>volumeBottom-value/maxVolume.value*(volumeBottom-volumeTop)
const sy=(value:number)=>scoreBottom-Math.max(0,Math.min(1,value))*(scoreBottom-scoreTop)
const candleWidth=computed(()=>Math.max(2,Math.min(8,(width-padding*2)/Math.max(visible.value.length,1)*.62)))
const scorePoints=computed(()=>visible.value.map((bar,index)=>{const signal=signalMap.value.get(bar.date);return signal?`${x(index)},${sy(Number(signal.probability))}`:null}).filter(Boolean).join(' '))
const overviewPrices=computed(()=>props.bars.map(item=>Number(item.close)).filter(Number.isFinite))
const overviewPoints=computed(()=>{
  const values=overviewPrices.value,min=Math.min(...values),max=Math.max(...values)
  return props.bars.map((bar,index)=>`${padding+index*(width-padding*2)/Math.max(props.bars.length-1,1)},${navigatorBottom-(Number(bar.close)-min)/(max-min||1)*(navigatorBottom-navigatorTop)}`).join(' ')
})
const navigatorX=computed(()=>padding+windowStart.value*(width-padding*2)/Math.max(props.bars.length,1))
const navigatorWidth=computed(()=>Math.max(8,windowSize.value*(width-padding*2)/Math.max(props.bars.length,1)))

function clampStart(value:number,size=windowSize.value){return Math.max(0,Math.min(Math.max(0,props.bars.length-size),value))}
function setWindow(size:number,center=windowStart.value+windowSize.value/2){
  const next=Math.max(Math.min(minWindow,props.bars.length),Math.min(props.bars.length,Math.round(size)))
  windowSize.value=next
  windowStart.value=clampStart(Math.round(center-next/2),next)
}
function resetView(){preset.value=160;setWindow(Math.min(160,props.bars.length),props.bars.length)}
function applyPreset(){if(preset.value===0)setWindow(props.bars.length,props.bars.length);else if(preset.value>0)setWindow(preset.value,props.bars.length)}
function pointX(event:MouseEvent|PointerEvent|WheelEvent){
  const rect=(event.currentTarget as SVGSVGElement).getBoundingClientRect()
  return Math.max(padding,Math.min(width-padding,(event.clientX-rect.left)*width/(rect.width||width)))
}
function onWheel(event:WheelEvent){
  if(!props.bars.length)return
  const relative=(pointX(event)-padding)/(width-padding*2)
  const center=windowStart.value+relative*Math.max(windowSize.value-1,0)
  preset.value=-1
  setWindow(windowSize.value*(event.deltaY<0?.78:1.28),center)
}
function startPan(event:PointerEvent){
  if(event.button!==0)return
  drag.value={x:event.clientX,start:windowStart.value,active:false}
  ;(event.currentTarget as SVGSVGElement).setPointerCapture?.(event.pointerId)
}
function movePan(event:PointerEvent){
  if(!drag.value)return
  const rect=(event.currentTarget as SVGSVGElement).getBoundingClientRect()
  const moved=Math.round((event.clientX-drag.value.x)*windowSize.value/(rect.width||width))
  if(Math.abs(moved)>1)drag.value.active=true
  windowStart.value=clampStart(drag.value.start-moved)
}
function endPan(event:PointerEvent){
  ;(event.currentTarget as SVGSVGElement).releasePointerCapture?.(event.pointerId)
  window.setTimeout(()=>{drag.value=null},0)
}
function recenterNavigator(event:PointerEvent){
  const relative=(pointX(event)-padding)/(width-padding*2)
  windowStart.value=clampStart(Math.round(relative*props.bars.length-windowSize.value/2))
}
function choose(value:any,date:string){if(!drag.value?.active)emit('select',{...value,date})}
watch(()=>props.bars,()=>resetView(),{immediate:true})
</script>

<template>
  <div class="trade-chart-shell">
    <div class="trade-chart-toolbar"><span>日 K · 成交量 · OOS 上涨概率 <small>滚轮缩放，空白处拖拽平移</small></span><div><span class="chart-window">{{visible.length}} / {{bars.length}} 日</span><select v-model.number="preset" @change="applyPreset"><option :value="60">60日</option><option :value="120">120日</option><option :value="160">160日</option><option :value="240">240日</option><option :value="0">全部</option><option :value="-1">自定义视图</option></select><button class="chart-reset" @click="resetView">重置</button></div></div>
    <svg v-if="visible.length" class="trade-chart" :class="{dragging:drag?.active}" :data-window-start="windowStart" :data-window-size="windowSize" :viewBox="`0 0 ${width} ${chartHeight}`" preserveAspectRatio="none" @wheel.prevent="onWheel" @pointerdown="startPan" @pointermove="movePan" @pointerup="endPan" @pointercancel="endPan">
      <line v-for="n in 5" :key="'grid'+n" :x1="padding" :x2="width-padding" :y1="priceTop+(n-1)*(priceBottom-priceTop)/4" :y2="priceTop+(n-1)*(priceBottom-priceTop)/4" class="chart-grid"/>
      <g v-for="(bar,index) in visible" :key="bar.date" class="candle" @pointerdown.stop @click.stop="choose(signalMap.get(bar.date)||{},bar.date)">
        <line :x1="x(index)" :x2="x(index)" :y1="py(Number(bar.high))" :y2="py(Number(bar.low))" :class="Number(bar.close)>=Number(bar.open)?'up':'down'"/>
        <rect :x="x(index)-candleWidth/2" :y="Math.min(py(Number(bar.open)),py(Number(bar.close)))" :width="candleWidth" :height="Math.max(1,Math.abs(py(Number(bar.open))-py(Number(bar.close))))" :class="Number(bar.close)>=Number(bar.open)?'up':'down'"/>
        <rect :x="x(index)-candleWidth/2" :y="vy(Number(bar.volume)||0)" :width="candleWidth" :height="volumeBottom-vy(Number(bar.volume)||0)" :class="Number(bar.close)>=Number(bar.open)?'volume-up':'volume-down'"/>
        <title>{{bar.date}} 开 {{bar.open}} 高 {{bar.high}} 低 {{bar.low}} 收 {{bar.close}}</title>
      </g>
      <polyline v-if="scorePoints" :points="scorePoints" class="score-line"/>
      <g v-for="(bar,index) in visible" :key="'score'+bar.date">
        <circle v-if="signalMap.get(bar.date)" :cx="x(index)" :cy="sy(Number(signalMap.get(bar.date)?.probability))" r="2.6" class="score-dot" @pointerdown.stop @click.stop="choose(signalMap.get(bar.date),bar.date)"/>
        <g v-for="(event,eventIndex) in eventMap.get(bar.date)||[]" :key="eventIndex" class="event-marker" @pointerdown.stop @click.stop="choose(event,bar.date)">
          <circle :cx="x(index)" :cy="event.action?.includes('BUY')?py(Number(bar.low))+15:py(Number(bar.high))-15" r="10" :class="event.action?.includes('BUY')?'buy-marker':'sell-marker'"/>
          <text :x="x(index)" :y="(event.action?.includes('BUY')?py(Number(bar.low))+19:py(Number(bar.high))-11)" text-anchor="middle">{{event.action?.includes('BUY')?'B':'S'}}</text>
        </g>
      </g>
      <text x="8" y="34" class="axis-label">价格</text><text x="8" :y="volumeTop+12" class="axis-label">量</text><text x="8" :y="scoreTop+12" class="axis-label">概率</text>
      <line :x1="padding" :x2="width-padding" :y1="scoreBottom" :y2="scoreBottom" class="chart-grid"/>
      <text :x="padding" y="510" class="date-label">{{visible[0]?.date}}</text><text :x="width-padding" y="510" text-anchor="end" class="date-label">{{visible[visible.length-1]?.date}}</text>
      <g class="chart-navigator" @pointerdown.stop="recenterNavigator"><rect :x="padding" :y="navigatorTop" :width="width-padding*2" :height="navigatorBottom-navigatorTop" class="navigator-track"/><polyline :points="overviewPoints" class="navigator-close"/><rect :x="navigatorX" :y="navigatorTop" :width="navigatorWidth" :height="navigatorBottom-navigatorTop" class="navigator-window"/></g>
      <text x="8" :y="navigatorTop+15" class="axis-label">导航</text>
    </svg>
    <div v-else class="empty">该区间没有可展示行情。</div>
    <div class="chart-legend"><span><i class="legend-buy"></i>真实买入/拒买</span><span><i class="legend-sell"></i>真实卖出/拒卖</span><span><i class="legend-score"></i>CV OOS 概率</span></div>
  </div>
</template>
