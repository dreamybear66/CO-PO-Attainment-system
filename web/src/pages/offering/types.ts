import type { CoRow } from '../../components/CoLadder'
import type { MapCell, PoRow } from '../../components/CoPoMatrix'
import type { Offering } from '../Offerings'

export type Assessment = {
  assessment_id: number; name: string; type: string; max_marks: string; locked: boolean; locked_at: string | null
  questions: number; marks_entered: number; marks_expected: number; unlock_status: string | null
}
export type Config = {
  config_id: number; target_pct: string; l3_pct: string; l2_pct: string; l1_pct: string
  direct_weight: string; indirect_weight: string; co_target_level: string; po_target_level: string
  valid_from: string; valid_to: string | null; rc_min_n: number; rc_min_r: string
  rc_max_depth: number; rc_depth_decay: string; favourable_rating: number
  component_weights: Record<string, number>
}
export type OfferingDetail = Offering & {
  faculty_id: number; enrolled: number; assessments: Assessment[]
  cos: { co_id: number; co_number: number; statement: string; bloom_level: number }[]
  config: Config | null
}
export type FollowUp = {
  action_id: number; co_id: number; co_number: number; offering_id: number; status: string; source: string
  description: string; level_before: string | null; level_after: string | null; change: string | null
  follow_up_offering_id: number | null; from_year: string; follow_up_year: string | null
}
export type AttainmentData = {
  cos: (CoRow & { students: number; respondents: number | null; pct_favourable: string | null; computed_at: string; config_id: number })[]
  pos: PoRow[]
  map: MapCell[]
  actions: FollowUp[]
}
