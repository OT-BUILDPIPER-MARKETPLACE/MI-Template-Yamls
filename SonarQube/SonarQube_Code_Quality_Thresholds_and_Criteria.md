# SonarQube MI - Code Quality Thresholds and Criteria

The following thresholds are used to evaluate the quality of code, covering **Security Rating**, **Blocker Violations**, **Major Violations**, **Bugs**, and **Code Smells**. These criteria help assess the overall code health and ensure adherence to coding best practices.

### Suggested Thresholds for Pass/Fail Criteria:

| S.No. | Category               | Elite             | High               | Medium            | Low                |
|-------|------------------------|-------------------|--------------------|-------------------|--------------------|
| 1     | Security Rating         | ≤ 50              | 50–300             | 300–500           | ≥ 600              |
| 2     | Blocker Violations      | ≤ 500             | 500–1000           | 1000–2000         | ≥ 2000             |
| 3     | Major Violations        | ≤ 500             | 500–1000           | 1000–2000         | ≥ 2000             |
| 4     | Bugs                    | ≤ 500             | 500–1000           | 1000–2000         | ≥ 2000             |
| 5     | Code Smells             | ≤ 500             | 500–1000           | 1000–2000         | ≥ 2000             |

### Key Points

#### 1. **Security Rating:**
   - **Elite:** ≤ 50
   - **High:** 50–300
   - **Medium:** 300–500
   - **Low:** ≥ 600
   - **Explanation:** Measures the overall security level of the codebase. A lower security rating indicates fewer vulnerabilities, contributing to a more secure application. This reflects the effectiveness of secure coding practices and vulnerability management.

#### 2. **Blocker Violations:**
   - **Elite:** ≤ 500
   - **High:** 500–1000
   - **Medium:** 1000–2000
   - **Low:** ≥ 2000
   - **Explanation:** Blocker violations are critical issues that could lead to severe system failures or security vulnerabilities. These violations demand immediate attention as they significantly impact functionality and security. Minimizing blocker violations ensures a stable, secure, and functional application.

#### 3. **Major Violations:**
   - **Elite:** ≤ 500
   - **High:** 500–1000
   - **Medium:** 1000–2000
   - **Low:** ≥ 2000
   - **Explanation:** Major violations are significant issues that affect code maintainability and performance. While not as critical as blocker violations, addressing them reduces technical debt, improves maintainability, and lowers future maintenance costs.

#### 4. **Bugs:**
   - **Elite:** ≤ 500
   - **High:** 500–1000
   - **Medium:** 1000–2000
   - **Low:** ≥ 2000
   - **Explanation:** Bugs represent code defects that can lead to unexpected behavior or system failures. Fewer bugs translate into higher reliability and better user satisfaction, reflecting robust testing and debugging practices.

#### 5. **Code Smells:**
   - **Elite:** ≤ 500
   - **High:** 500–1000
   - **Medium:** 1000–2000
   - **Low:** ≥ 2000
   - **Explanation:** Code smells indicate issues with code maintainability that don't directly affect functionality but make it harder to work with. Minimizing code smells ensures better readability, scalability, and long-term maintainability, reducing development and maintenance overhead.

---

### Explanation of Categories:

- **Elite:** Represents top-tier code quality with minimal violations and issues, ensuring high standards of security, performance, and maintainability.
- **High:** Slightly more lenient but still enforces a strong standard for code quality. It indicates a well-maintained and secure codebase.
- **Medium:** Allows a moderate number of issues, suitable for systems with non-critical functions or those in transition.
- **Low:** Indicates a significant number of issues, typically resulting in a failed evaluation. Poor code quality can lead to increased maintenance costs and security risks.

---

### Conclusion:
- **Low and Medium levels** of violations and bugs often signal areas for improvement that can escalate into bigger issues over time.
- **High and Blocker violations** must be addressed immediately to protect the system from potential vulnerabilities and failure.
- **Security Rating** provides an overall view of code security, guiding the prioritization of improvements.
- **Bugs and Code Smells** directly affect system reliability and maintainability, and minimizing them ensures a better long-term development experience.

---