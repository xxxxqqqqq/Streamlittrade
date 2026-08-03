<script setup lang="ts">
import {computed} from 'vue'
const props=defineProps<{page:number;total:number;pageSize:number}>()
const emit=defineEmits<{change:[page:number]}>()
const pages=computed(()=>Math.max(1,Math.ceil(props.total/props.pageSize)))
</script>
<template><div class="paginator"><span>共 {{total}} 条 · 第 {{page}} / {{pages}} 页</span><div><button class="secondary" :disabled="page<=1" @click="emit('change',page-1)">上一页</button><button class="secondary" :disabled="page>=pages" @click="emit('change',page+1)">下一页</button></div></div></template>
