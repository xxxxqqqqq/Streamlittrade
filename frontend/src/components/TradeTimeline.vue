<script setup lang="ts">
defineProps<{events:any[]}>()
const label=(action:string)=>({BUY:'买入成交',SELL:'卖出成交',REJECT_BUY:'买入拒单',REJECT_SELL:'卖出拒单'} as any)[action]||action
</script>

<template>
  <div class="trade-timeline">
    <article v-for="(event,index) in events" :key="index" class="timeline-event" :class="String(event.action).toLowerCase()">
      <i></i><div><b>{{label(event.action)}} · {{event.date}}</b><p v-if="event.signal_date">{{event.signal_date}} 收盘生成信号 → {{event.date}} 尝试成交</p><p>{{event.shares||'—'}} 股 · {{event.price??'—'}} 元 · {{event.reason||'按模型目标组合执行'}}</p><small v-if="event.pnl!==undefined">扣费后损益 {{Number(event.pnl).toFixed(2)}} 元（{{Number(event.profit_pct||0).toFixed(2)}}%）</small></div>
    </article>
    <div v-if="!events.length" class="empty">该股票在当前回测中没有成交或拒单事件。</div>
  </div>
</template>
