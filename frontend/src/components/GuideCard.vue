<script setup lang="ts">
import type {Component} from 'vue'

// 每页顶部的一句话说明卡：图标 + "这一步在干什么" + 一句人话。
// 组件只负责统一版式，文案一律由页面传入。
defineProps<{icon?:Component|string;title:string;text:string}>()
</script>

<template>
  <article class="guide-card">
    <i class="guide-icon">
      <component :is="icon" v-if="icon&&typeof icon!=='string'" :size="21"/>
      <template v-else>💡</template>
    </i>
    <div class="guide-copy"><b>{{title}}</b><p>{{text}}</p></div>
  </article>
</template>

<style scoped>
.guide-card{display:flex;align-items:flex-start;gap:14px;margin-bottom:16px;padding:18px 20px;border:1px solid #e3e1fb;border-radius:14px;background:linear-gradient(135deg,#eef0ff,#f8f6ff);box-shadow:0 1px 3px #1018280f}
.guide-icon{width:42px;height:42px;flex:none;border-radius:11px;background:#fff;color:#4f46e5;display:grid;place-items:center;font-size:19px;font-style:normal;box-shadow:0 1px 3px #10182814}
.guide-copy b{font-size:15px;color:#1a2233}
.guide-copy p{margin:3px 0 0;color:#5b6474;font-size:13px;line-height:1.6}
@media(max-width:720px){.guide-card{padding:15px 16px}.guide-icon{width:36px;height:36px}}
</style>
