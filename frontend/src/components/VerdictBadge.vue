<script setup lang="ts">
import {computed} from 'vue'
import {VERDICT_COLORS,type Verdict,type VerdictLevel} from '../verdict'

// 判断徽标的唯一出口：判断文案与阈值依据全部来自 verdict.ts，页面不得自己拼判断。
const props=defineProps<{verdict:Verdict|null}>()
const glyph:Record<VerdictLevel,string>={good:'✓',ok:'✓',warn:'⚠',weak:'—',bad:'✗',na:'·'}
const tone=computed(()=>props.verdict?VERDICT_COLORS[props.verdict.level]:'n')
const text=computed(()=>props.verdict?`${glyph[props.verdict.level]} ${props.verdict.label}`:'')
</script>

<template>
  <i v-if="verdict" class="verdict-badge" :class="tone" :title="verdict.hint||undefined">{{text}}</i>
</template>

<style scoped>
.verdict-badge{display:inline-flex;align-items:center;padding:3px 9px;border-radius:99px;background:#eef0f4;color:#5b6474;font-style:normal;font-size:11px;font-weight:600;white-space:nowrap}
.verdict-badge.g{background:#e9f7ef;color:#16a34a}
.verdict-badge.p{background:#eef0ff;color:#4f46e5}
.verdict-badge.w{background:#fdf3e3;color:#d97706}
.verdict-badge.b{background:#fdecec;color:#dc2626}
</style>
