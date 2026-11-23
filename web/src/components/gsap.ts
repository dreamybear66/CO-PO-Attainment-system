// GSAP set-up shared by the timeline animations (CO ladder, CO-PO matrix, charts, sign-in network).
import { useGSAP } from '@gsap/react'
import gsap from 'gsap'

gsap.registerPlugin(useGSAP)
gsap.defaults({ ease: 'power3.out', duration: 0.7 })

/** True when the visitor asked for less motion; timelines then jump to their end state. */
export const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

export { gsap, useGSAP }
