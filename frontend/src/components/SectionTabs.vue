<script setup lang="ts">
import {computed} from 'vue'
import {useRoute} from 'vue-router'
import {activeSectionTab,type SectionTab} from '../sections'

// 五段内部的次级入口统一用页签表达，不再放回侧栏：同一个段内切换视图时，
// 顶栏高亮和页签高亮始终落在同一个研究对象上。
const props=defineProps<{tabs:readonly SectionTab[];label?:string}>()
const route=useRoute()
const current=computed(()=>activeSectionTab(route.path,route.query,props.tabs))
function tabKey(tab:SectionTab){return tab.to+(tab.query?`?${JSON.stringify(tab.query)}`:'')}
</script>

<template>
  <nav class="section-tabs" :aria-label="label||'分段页签'">
    <RouterLink
      v-for="tab in tabs"
      :key="tabKey(tab)"
      class="section-tab"
      :class="{active:current===tab}"
      :aria-current="current===tab?'page':undefined"
      :to="tab.query?{path:tab.to,query:tab.query}:tab.to"
    >{{tab.label}}</RouterLink>
  </nav>
</template>
