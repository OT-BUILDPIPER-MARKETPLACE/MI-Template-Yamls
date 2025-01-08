# PRISMA MI - Security Vulnerability Thresholds

The following thresholds are used to evaluate the severity of vulnerabilities found in the system, categorized by **Low**, **Medium**, **High**, and **Critical** impact. These thresholds provide the basis for determining the pass/fail status of security scans.

## Suggested Thresholds for Pass/Fail Criteria:

| S.No. | Category                          | Elite             | High                 | Medium                | Low               |
|-------|-----------------------------------|-------------------|----------------------|-----------------------|-------------------|
| 1     | Vulnerabilities (LOW)             | ≤ 2               | 2–10                 | 10–15                 | ≥ 15              |
| 2     | Vulnerabilities (MEDIUM)          | ≤ 30              | 30–40                | 40–60                 | ≥ 60              |
| 3     | Vulnerabilities (HIGH)            | ≤ 30              | 30–40                | 40–60                 | ≥ 60              |
| 4     | Vulnerabilities (CRITICAL)        | ≤ 1               | 1–5                  | 5–10                  | ≥ 10              |
| 5     | Vulnerabilities (TOTAL)           | ≤ 50              | 50–75                | 75–100                | ≥ 100             |

## Key Points

### 1. **Vulnerabilities (LOW):**
   - **Elite:** ≤ 2
   - **High:** Between 2 and 10
   - **Medium:** Between 10 and 15
   - **Low:** ≥ 15
   - **Explanation:** Measures the number of low-severity vulnerabilities in the system. While these are less likely to be exploited, they still reflect areas for improvement. A high count could indicate emerging risks or overlooked details.

### 2. **Vulnerabilities (MEDIUM):**
   - **Elite:** ≤ 30
   - **High:** Between 30 and 40
   - **Medium:** Between 40 and 60
   - **Low:** ≥ 60
   - **Explanation:** This category includes vulnerabilities with moderate severity levels, which could balance the potential for exploitation with the impact. Addressing these is crucial for improving the security posture.

### 3. **Vulnerabilities (HIGH):**
   - **Elite:** ≤ 30
   - **High:** Between 30 and 40
   - **Medium:** Between 40 and 60
   - **Low:** ≥ 60
   - **Explanation:** High-severity vulnerabilities can be exploited to cause significant damage. They need immediate resolution to minimize risks and potential system disruption.

### 4. **Vulnerabilities (CRITICAL):**
   - **Elite:** ≤ 1
   - **High:** Between 1 and 5
   - **Medium:** Between 5 and 10
   - **Low:** ≥ 10
   - **Explanation:** Critical vulnerabilities pose the highest level of risk to the system and require urgent resolution. They can lead to data breaches, service disruptions, or serious reputational damage.

### 5. **Vulnerabilities (TOTAL):**
   - **Elite:** ≤ 50
   - **High:** Between 50 and 75
   - **Medium:** Between 75 and 100
   - **Low:** ≥ 100
   - **Explanation:** This is the total count of all vulnerabilities across all severity levels. A high total count indicates widespread security issues, warranting a comprehensive review of security practices.

---

## Explanation of Categories:

- **Elite:** Represents a highly secure system with minimal vulnerabilities. It is the gold standard in security compliance.
- **High:** Slightly more lenient, but still reflects strong security standards and good management of vulnerabilities.
- **Medium:** Allows a moderate number of vulnerabilities and might be suitable for systems with non-critical functions or in transition.
- **Low:** Indicates a significant number of vulnerabilities, typically leading to a failure in the evaluation. Security hygiene is a major concern at this level.

---

## Conclusion:
- **Low and Medium vulnerabilities** indicate weak spots that can worsen over time if not addressed.
- **High and Critical vulnerabilities** must be resolved immediately to protect the system from severe risks.
- **Total vulnerabilities** give a comprehensive overview of the security health of the system, helping prioritize remediation efforts.
