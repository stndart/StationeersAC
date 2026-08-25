/** Game constants for the Stationeers phase-change cascade model. */

export const TICK_S = 0.5;
export const R = 8.314462618; // J/(mol K)
export const P_ATM = 101.325; // kPa
export const P_MAX_LIQUID_KPA = 6000.0;

export const LIQUID_FEED_L_PER_TICK = 0.25;
export const EVAP_TARGET_L = 20.0;
export const CHAMBER_VOLUME_L = 200.0;
export const DEFAULT_LIQUID_PIPE_L = 100.0;
export const LIQUID_PIPE_FILL_MAX = 0.8;

export const CHAMBER_HX_M2 = 15.0;
export const CHAMBER_HX_J_PER_TICK_K = 100.0 * CHAMBER_HX_M2 * TICK_S; // 750
export const PIPE_CONV_THERMAL = 1.05;
export const RAD_J_PER_TICK_K = PIPE_CONV_THERMAL * 50.0; // 52.5

export const CFHE_ETA_PER_UNIT = 0.7;
export const MAX_CFHE = 6;
export const DEFAULT_HX_LOOP_KPA = 300.0;

export const MARGIN_K = 5.0;
export const TIGHT_MARGIN_K = 5.0;
export const DUMP_RAD_DT_K = 15.0;
export const K = 273.15;
