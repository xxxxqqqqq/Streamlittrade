<script setup lang="ts">
import type {VerdictLevel} from '../verdict'

// 结论卡：结果页最上面的一块，先说结论再给数字。
// 级别决定左侧色条与底色，正文由使用方用插槽写"这意味着什么"。
defineProps<{level?:VerdictLevel}>()
</script>

<template>
  <article class="verdict-card" :class="level||'na'">
    <slot/>
  </article>
</template>

<style scoped>
.verdict-card{margin-bottom:16px;padding:18px 20px;border:1px solid #e7e9ee;border-left:4px solid #98a0ae;border-radius:14px;background:#fff;box-shadow:0 1px 3px #1018280f;color:#1a2233}
.verdict-card.good{border-left-color:#16a34a;background:#f1fbf5}
.verdict-card.ok{border-left-color:#4f46e5;background:#f6f6ff}
.verdict-card.warn,.verdict-card.weak{border-left-color:#d97706;background:#fdf8ee}
.verdict-card.bad{border-left-color:#dc2626;background:#fdf2f2}
.verdict-card :deep(b){font-size:15px}
.verdict-card :deep(p){margin:6px 0 0;color:#5b6474;font-size:13px;line-height:1.7}
</style>
