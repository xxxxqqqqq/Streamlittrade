<script setup lang="ts">
import {computed} from 'vue'
import {statusLabel,statusTone} from '../status'

const props=defineProps<{status?:string|null;label?:string}>()

const text=computed(()=>props.label||statusLabel(props.status)||'—')
const tone=computed(()=>statusTone(props.status))
</script>

<template><i class="status" :class="tone">{{text}}</i></template>
