<script setup lang="ts">
import {computed,ref} from 'vue'

const props=defineProps<{bars:any[];signals:any[];events:any[]}>()
const emit=defineEmits<{select:[value:any]}>()
const limit=ref(160)
const width=1000,padding=46,priceTop=20,priceBottom=325,volumeTop=342,volumeBottom=410,scoreTop=438,scoreBottom=510
const visible=computed(()=>limit.value?props.bars.slice(-limit.value):props.bars)
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
function choose(value:any,date:string){emit('select',{...value,date})}
</script>

<template>
  <div class="trade-chart-shell">
    <div class="trade-chart-toolbar"><span>日 K · 成交量 · OOS 上涨概率</span><select v-model.number="limit"><option :value="60">60日</option><option :value="120">120日</option><option :value="160">160日</option><option :value="240">240日</option><option :value="0">全部</option></select></div>
    <svg v-if="visible.length" class="trade-chart" :viewBox="`0 0 ${width} 535`" preserveAspectRatio="none">
      <line v-for="n in 5" :key="'grid'+n" :x1="padding" :x2="width-padding" :y1="priceTop+(n-1)*(priceBottom-priceTop)/4" :y2="priceTop+(n-1)*(priceBottom-priceTop)/4" class="chart-grid"/>
      <g v-for="(bar,index) in visible" :key="bar.date" class="candle" @click="choose(signalMap.get(bar.date)||{},bar.date)">
        <line :x1="x(index)" :x2="x(index)" :y1="py(Number(bar.high))" :y2="py(Number(bar.low))" :class="Number(bar.close)>=Number(bar.open)?'up':'down'"/>
        <rect :x="x(index)-candleWidth/2" :y="Math.min(py(Number(bar.open)),py(Number(bar.close)))" :width="candleWidth" :height="Math.max(1,Math.abs(py(Number(bar.open))-py(Number(bar.close))))" :class="Number(bar.close)>=Number(bar.open)?'up':'down'"/>
        <rect :x="x(index)-candleWidth/2" :y="vy(Number(bar.volume)||0)" :width="candleWidth" :height="volumeBottom-vy(Number(bar.volume)||0)" :class="Number(bar.close)>=Number(bar.open)?'volume-up':'volume-down'"/>
        <title>{{bar.date}} 开 {{bar.open}} 高 {{bar.high}} 低 {{bar.low}} 收 {{bar.close}}</title>
      </g>
      <polyline v-if="scorePoints" :points="scorePoints" class="score-line"/>
      <g v-for="(bar,index) in visible" :key="'score'+bar.date">
        <circle v-if="signalMap.get(bar.date)" :cx="x(index)" :cy="sy(Number(signalMap.get(bar.date)?.probability))" r="2.6" class="score-dot" @click="choose(signalMap.get(bar.date),bar.date)"/>
        <g v-for="(event,eventIndex) in eventMap.get(bar.date)||[]" :key="eventIndex" class="event-marker" @click.stop="choose(event,bar.date)">
          <circle :cx="x(index)" :cy="event.action?.includes('BUY')?py(Number(bar.low))+15:py(Number(bar.high))-15" r="10" :class="event.action?.includes('BUY')?'buy-marker':'sell-marker'"/>
          <text :x="x(index)" :y="(event.action?.includes('BUY')?py(Number(bar.low))+19:py(Number(bar.high))-11)" text-anchor="middle">{{event.action?.includes('BUY')?'B':'S'}}</text>
        </g>
      </g>
      <text x="8" y="34" class="axis-label">价格</text><text x="8" :y="volumeTop+12" class="axis-label">量</text><text x="8" :y="scoreTop+12" class="axis-label">概率</text>
      <line :x1="padding" :x2="width-padding" :y1="scoreBottom" :y2="scoreBottom" class="chart-grid"/>
      <text :x="padding" y="530" class="date-label">{{visible[0]?.date}}</text><text :x="width-padding" y="530" text-anchor="end" class="date-label">{{visible[visible.length-1]?.date}}</text>
    </svg>
    <div v-else class="empty">该区间没有可展示行情。</div>
    <div class="chart-legend"><span><i class="legend-buy"></i>真实买入/拒买</span><span><i class="legend-sell"></i>真实卖出/拒卖</span><span><i class="legend-score"></i>CV OOS 概率</span></div>
  </div>
</template>
