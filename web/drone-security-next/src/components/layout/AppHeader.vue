<template>
  <header class="app-header">
    <div class="header-copy">
      <p class="eyebrow">power cyber range</p>
      <h1>电力攻防演示平台</h1>
    </div>

    <div class="header-runtime">
      <div class="runtime-badge" :class="lineStateClass">
        {{ runtime.mode }}
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  runtime: {
    type: Object,
    required: true,
  },
  lineState: {
    type: String,
    required: true,
  },
})

const lineStateClass = computed(() => ({
  normal: props.lineState === 'normal',
  overload: props.lineState === 'overload',
  off: props.lineState === 'no-current',
}))
</script>

<style scoped>
.app-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  padding: 8px 12px;
  border: 1px solid var(--border-soft);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(14, 35, 56, 0.96) 0%, rgba(7, 18, 30, 0.92) 100%);
  box-shadow: var(--shadow-panel);
}

.eyebrow {
  margin: 0 0 4px;
  color: var(--brand-cyan);
  font-size: 9px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 16px;
  line-height: 1.05;
}

.header-runtime {
  min-width: 0;
}

.runtime-badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(93, 255, 178, 0.12);
  color: var(--brand-green);
  font-size: 11px;
  font-weight: 700;
  border: 1px solid var(--border-soft);
}

.runtime-badge.overload {
  background: rgba(255, 100, 110, 0.12);
  color: var(--brand-red);
}

.runtime-badge.off {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

@media (max-width: 1100px) {
  .app-header {
    grid-template-columns: 1fr;
  }

}
</style>
