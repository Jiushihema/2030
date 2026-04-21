<template>
  <section class="panel-shell">
    <div class="panel-head">
      <h2>攻击编排面板</h2>
    </div>

    <div class="section">
      <div class="section-label">攻击类型</div>
      <div class="attack-list">
        <button
          v-for="attack in attackOptions"
          :key="attack.id"
          type="button"
          class="attack-card"
          :class="{ active: attack.id === selectedAttackId }"
          @click="$emit('select-attack', attack.id)"
        >
          <span class="attack-icon">{{ attack.icon }}</span>
          <span class="attack-text">
            <strong>{{ attack.label }}</strong>
          </span>
        </button>
      </div>
    </div>

    <div class="section">
      <div class="section-label">{{ selectedAttack.selectionLabel }}</div>
      <select
        v-if="selectedAttack.targetMode === 'manual'"
        class="target-select"
        :value="selectedTargetId"
        @change="$emit('select-target', $event.target.value)"
      >
        <option
          v-for="target in selectedAttack.targets"
          :key="target.id"
          :value="target.id"
        >
          {{ target.label }}
        </option>
      </select>
      <div v-else class="auto-target">
        自动推演范围：{{ selectedAttack.autoTargetLabel }}
      </div>
    </div>

    <div class="section description-card">
      <div class="section-label">场景说明</div>
      <p>{{ selectedAttack.description }}</p>
    </div>

    <div class="section toggle-row">
      <div>
        <div class="section-label">{{ selectedAttack.autoDefenseLabel }}</div>
      </div>
      <label class="switch">
        <input
          type="checkbox"
          :checked="defenseEnabled"
          @change="$emit('toggle-defense', $event.target.checked)"
        />
        <span class="slider"></span>
      </label>
    </div>

    <div class="action-row">
      <button type="button" class="primary-btn" :disabled="isBusy" @click="$emit('launch')">
        {{ isBusy ? '攻击执行中...' : '发起攻击' }}
      </button>
      <button
        type="button"
        class="ghost-btn overload"
        @click="$emit('scenario', 'continuous-overvoltage')"
      >
        持续注入过压帧
      </button>
      <button type="button" class="ghost-btn overload" @click="$emit('scenario', 'overload')">
        负荷冲击
      </button>
      <button type="button" class="ghost-btn normal" @click="$emit('scenario', 'normal')">
        恢复正常
      </button>
    </div>

    <div class="status-box">
      <div class="section-label">运行状态</div>
      <p>{{ statusMessage }}</p>
    </div>

    <div v-if="attackResult" class="result-box">
      <div class="result-title">{{ attackResult.title }}</div>
      <ul>
        <li v-for="item in attackResult.impacts" :key="item">{{ item }}</li>
      </ul>
    </div>
  </section>
</template>

<script setup>
defineProps({
  attackOptions: {
    type: Array,
    required: true,
  },
  selectedAttackId: {
    type: String,
    required: true,
  },
  selectedTargetId: {
    type: String,
    default: 'auto',
  },
  selectedAttack: {
    type: Object,
    required: true,
  },
  defenseEnabled: {
    type: Boolean,
    required: true,
  },
  isBusy: {
    type: Boolean,
    required: true,
  },
  statusMessage: {
    type: String,
    required: true,
  },
  attackResult: {
    type: Object,
    default: null,
  },
  canDefend: {
    type: Boolean,
    required: true,
  },
})

defineEmits(['select-attack', 'select-target', 'toggle-defense', 'launch', 'defend-now', 'scenario'])
</script>

<style scoped>
.panel-shell {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
}

.panel-head h2 {
  margin: 0;
  font-size: 18px;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-label {
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.attack-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.attack-card {
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 8px;
  align-items: center;
  width: 100%;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid var(--border-soft);
  border-radius: 12px;
  background: rgba(7, 17, 30, 0.72);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, transform 0.2s ease, background 0.2s ease;
}

.attack-card:hover {
  transform: translateY(-1px);
  border-color: rgba(255, 100, 110, 0.36);
}

.attack-card.active {
  border-color: rgba(255, 100, 110, 0.62);
  background: rgba(255, 100, 110, 0.08);
}

.attack-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: rgba(75, 200, 255, 0.1);
  color: var(--brand-cyan);
  font-weight: 800;
  font-size: 12px;
}

.attack-text {
  min-width: 0;
}

.attack-text strong {
  display: block;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.target-select,
.auto-target,
.description-card,
.status-box,
.result-box,
.toggle-row {
  border: 1px solid var(--border-soft);
  border-radius: 14px;
  background: rgba(7, 17, 30, 0.72);
}

.target-select {
  width: 100%;
  padding: 10px 12px;
  color: var(--text-primary);
  background-color: rgba(7, 17, 30, 0.9);
  outline: none;
  font-size: 13px;
}

.auto-target {
  padding: 10px 12px;
  color: var(--brand-amber);
  font-size: 13px;
}

.description-card p,
.status-box p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.description-card,
.status-box,
.result-box,
.toggle-row {
  padding: 10px 12px;
}

.toggle-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.switch {
  position: relative;
  display: inline-flex;
  width: 46px;
  height: 26px;
}

.switch input {
  width: 0;
  height: 0;
  opacity: 0;
}

.slider {
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: rgba(255, 100, 110, 0.4);
  transition: 0.2s ease;
}

.slider::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 4px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: white;
  transition: 0.2s ease;
}

input:checked + .slider {
  background: rgba(93, 255, 178, 0.52);
}

input:checked + .slider::before {
  transform: translateX(20px);
}

.action-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.primary-btn,
.ghost-btn {
  min-height: 34px;
  padding: 0 8px;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
}

.primary-btn {
  background: linear-gradient(135deg, #3fb9ff 0%, #1d86ff 100%);
  color: white;
  font-weight: 700;
}

.primary-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.ghost-btn {
  border: 1px solid var(--border-soft);
  background: rgba(7, 17, 30, 0.72);
  color: var(--text-primary);
}

.ghost-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.ghost-btn.overload {
  color: var(--brand-amber);
}

.ghost-btn.normal {
  color: var(--brand-green);
}

.ghost-btn.defend {
  color: var(--brand-cyan);
}

.result-title {
  color: var(--brand-green);
  font-weight: 700;
}

.result-box ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}

@media (max-width: 1280px) {
  .attack-list,
  .action-row {
    grid-template-columns: 1fr;
  }
}
</style>
