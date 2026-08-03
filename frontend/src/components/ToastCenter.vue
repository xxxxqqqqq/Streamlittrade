<script setup lang="ts">
import {dismissToast,toasts} from '../ui'
import {CircleCheck,Info,X,XCircle} from 'lucide-vue-next'
</script>
<template><div class="toast-stack" aria-live="polite"><div v-for="item in toasts" :key="item.id" class="toast" :class="item.kind"><XCircle v-if="item.kind==='error'" :size="18"/><CircleCheck v-else-if="item.kind==='success'" :size="18"/><Info v-else :size="18"/><span>{{item.message}}</span><button aria-label="关闭提示" @click="dismissToast(item.id)"><X :size="14"/></button></div></div></template>
