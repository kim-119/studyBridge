import { useCallback, useMemo, useState } from 'react';
import {
  MAX_AGENT_COUNT,
  MIN_AGENT_COUNT,
  applyMateType,
  buildCreateRoomPayload,
  makeDefaultAgents,
  mapPresetAgentToDraft,
  nextAgentDraft,
  normalizeAgentDrafts,
} from './agentDrafts';
import { DEFAULT_DEBATE_CONFIG, DEFAULT_SIMULATION_CONFIG, DEFAULT_SOCRATIC_CONFIG } from './learningModes';
import { presetsForMode } from './roomPresets';

function initialDraft() {
  return {
    roomName: '',
    learningMode: 'basic',
    debateConfig: DEFAULT_DEBATE_CONFIG,
    socraticConfig: DEFAULT_SOCRATIC_CONFIG,
    simulationConfig: DEFAULT_SIMULATION_CONFIG,
    agentDrafts: makeDefaultAgents(),
    selectedPresetId: null,
    presetIndex: 0,
    step: 0,
  };
}

function presetConfigPatch(preset, draft) {
  if (preset.mode === 'socratic') {
    return { socraticConfig: { ...draft.socraticConfig, questionIntensity: preset.questionIntensity, hintPolicy: preset.hintPolicy } };
  }
  if (preset.mode === 'debate') {
    return { debateConfig: { ...draft.debateConfig, debateStrength: preset.debateStrength } };
  }
  if (preset.mode === 'simulation') {
    return { simulationConfig: { ...draft.simulationConfig, scenarioType: preset.scenarioType, difficulty: preset.difficulty } };
  }
  return {};
}

export function useRoomDraft() {
  const [draft, setDraft] = useState(initialDraft);

  const update = useCallback((patch) => setDraft((previous) => ({ ...previous, ...patch })), []);
  const reset = useCallback(() => setDraft(initialDraft()), []);

  const presets = useMemo(() => presetsForMode(draft.learningMode), [draft.learningMode]);
  const activePreset = presets.find((preset) => preset.id === draft.selectedPresetId) || null;

  const selectMode = useCallback(
    (learningMode) =>
      update({
        learningMode,
        selectedPresetId: null,
        presetIndex: 0,
        debateConfig: DEFAULT_DEBATE_CONFIG,
        socraticConfig: DEFAULT_SOCRATIC_CONFIG,
        simulationConfig: DEFAULT_SIMULATION_CONFIG,
      }),
    [update]
  );

  const applyPreset = useCallback((preset) => {
    setDraft((previous) => ({
      ...previous,
      ...presetConfigPatch(preset, previous),
      selectedPresetId: preset.id,
      learningMode: preset.mode,
      roomName: preset.roomName,
      agentDrafts: preset.agents.slice(0, MAX_AGENT_COUNT).map(mapPresetAgentToDraft),
      step: 0,
    }));
  }, []);

  const showPreset = useCallback(
    (index) => update({ presetIndex: Math.max(0, Math.min(index, presets.length - 1)) }),
    [presets.length, update]
  );

  const updateConfig = useCallback(
    (configKey, patch) => setDraft((previous) => ({ ...previous, [configKey]: { ...previous[configKey], ...patch } })),
    []
  );

  const updateAgent = useCallback((index, patch) => {
    setDraft((previous) => {
      const agentDrafts = [...previous.agentDrafts];
      agentDrafts[index] = { ...agentDrafts[index], ...patch };
      return { ...previous, agentDrafts };
    });
  }, []);

  const chooseMateType = useCallback((index, mateTypeKey) => {
    setDraft((previous) => ({ ...previous, agentDrafts: applyMateType(previous.agentDrafts, index, mateTypeKey) }));
  }, []);

  const ensureAgent = (previous, index) => {
    const agentDrafts = normalizeAgentDrafts(previous.agentDrafts);
    while (agentDrafts.length <= index && agentDrafts.length < MAX_AGENT_COUNT) {
      agentDrafts.push(nextAgentDraft(agentDrafts.length, activePreset));
    }
    return agentDrafts;
  };

  const goNext = () => {
    setDraft((previous) => {
      if (previous.step >= MAX_AGENT_COUNT) return previous;
      return { ...previous, agentDrafts: ensureAgent(previous, previous.step), step: previous.step + 1 };
    });
  };

  const goPrevious = () => update({ step: Math.max(0, draft.step - 1) });

  const addAgent = () => {
    setDraft((previous) => {
      const agentDrafts = normalizeAgentDrafts(previous.agentDrafts);
      if (agentDrafts.length >= MAX_AGENT_COUNT) return previous;
      const next = [...agentDrafts, nextAgentDraft(agentDrafts.length, activePreset)];
      return { ...previous, agentDrafts: next, step: next.length };
    });
  };

  const removeAgent = () => {
    setDraft((previous) => {
      const agentDrafts = normalizeAgentDrafts(previous.agentDrafts);
      if (agentDrafts.length <= MIN_AGENT_COUNT) return previous;
      const next = agentDrafts.slice(0, -1);
      return { ...previous, agentDrafts: next, step: Math.min(previous.step, next.length) };
    });
  };

  return {
    draft,
    presets,
    update,
    reset,
    selectMode,
    applyPreset,
    showPreset,
    updateConfig,
    updateAgent,
    chooseMateType,
    goNext,
    goPrevious,
    addAgent,
    removeAgent,
    buildPayload: () => buildCreateRoomPayload(draft),
  };
}
