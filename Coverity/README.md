# **COVERITY MI Thresholds and Criteria**

## **Coverage Categories**

| **S.No.** | **Category**          | **<span style='color: purple;'>Elite</span>**      | **<span style='color: blue;'>High</span>**        | **<span style='color: green;'>Medium</span>**      | **<span style='color: yellow;'>Low</span>**        |
| --------- | --------------------- | ---------------------- | ----------------- | ----------------- | ---------------------- |
| **1**     | **High Impact Count**  | ≤ 20                  | 20–50             | 50–75             | ≥ 100                  |
| **2**     | **Outstanding**        | ≤ 100                 | 100–200           | 200–300           | ≥ 300                  |
| **3**     | **Triaged**            | ≤ 5                   | 5–10              | 10–15             | ≥ 15                   |
| **4**     | **Security Issues**    | ≤ 5                   | 5–10              | 10–15             | ≥ 15                   |
| **5**     | **Quality Issues**     | ≤ 100                 | 100–200           | 200–300           | ≥ 300                  |

---

## **Suggested Thresholds for Pass/Fail Criteria**

### **COVERITY MI Criteria:**

- **<span style='color: purple;'>Elite</span>**: ≤ 20 for High Impact Count, ≤ 100 for Outstanding, ≤ 5 for Triaged, ≤ 5 for Security Issues, and ≤ 100 for Quality Issues.
- **<span style='color: blue;'>High</span>**: Between 20 and 50 for High Impact Count, Between 100 and 200 for Outstanding, Between 5 and 10 for Triaged, Between 5 and 10 for Security Issues, and Between 100 and 200 for Quality Issues.
- **<span style='color: green;'>Medium</span>**: Between 50 and 75 for High Impact Count, Between 200 and 300 for Outstanding, Between 10 and 15 for Triaged, Between 10 and 15 for Security Issues, and Between 200 and 300 for Quality Issues.
- **<span style='color: yellow;'>Low</span>**: ≥ 100 for High Impact Count, ≥ 300 for Outstanding, ≥ 15 for Triaged, ≥ 15 for Security Issues, and ≥ 300 for Quality Issues.

---

## **Explanation**

### **<span style='color: purple;'>Elite</span> Criteria:**

- **High Impact Count**: ≤ 20.
- **Explanation**: Represents exceptional code quality with minimal high-impact issues. The system remains stable, secure, and easy to maintain with very few critical vulnerabilities.

- **Outstanding Issues**: ≤ 100.
- **Explanation**: A small number of unresolved issues, which can be actively managed without accumulating technical debt, ensuring smoother long-term project maintenance.

- **Triaged Issues**: ≤ 5.
- **Explanation**: The system has a low number of issues under review, indicating active management and prioritization of critical areas. This leads to efficient issue resolution.

- **Security Issues**: ≤ 5.
- **Explanation**: Minimal security issues, ensuring that the codebase is secure and protected from potential vulnerabilities and exploits.

- **Quality Issues**: ≤ 100.
- **Explanation**: Excellent adherence to code quality standards, making the codebase easier to scale and enhance, with fewer maintenance challenges over time.

### **<span style='color: blue;'>High</span> Criteria:**

- **High Impact Count**: Between 20 and 50.
- **Explanation**: A moderate number of high-impact issues, still manageable but requiring attention to ensure long-term stability and security.

- **Outstanding Issues**: Between 100 and 200.
- **Explanation**: Some unresolved issues exist, but they do not significantly disrupt project progress. Further attention is needed to avoid accumulating technical debt.

- **Triaged Issues**: Between 5 and 10.
- **Explanation**: A reasonable number of issues are under review, indicating ongoing efforts to categorize and prioritize critical issues for resolution.

- **Security Issues**: Between 5 and 10.
- **Explanation**: A manageable number of security vulnerabilities, though further action is needed to reduce exposure to potential risks.

- **Quality Issues**: Between 100 and 200.
- **Explanation**: The code maintains a good level of quality, but there are still moderate challenges in terms of readability, maintainability, and adherence to best practices.

### **<span style='color: green;'>Medium</span> Criteria:**

- **High Impact Count**: Between 50 and 75.
- **Explanation**: A higher number of critical issues, which can affect system stability. Attention is needed to resolve these issues promptly.

- **Outstanding Issues**: Between 200 and 300.
- **Explanation**: A significant number of unresolved issues, which could potentially lead to accumulated technical debt and maintenance challenges if not addressed.

- **Triaged Issues**: Between 10 and 15.
- **Explanation**: An average number of issues that need to be reviewed and prioritized. There is some indication of delayed attention to issues that could impact progress.

- **Security Issues**: Between 10 and 15.
- **Explanation**: A moderate number of security vulnerabilities. Addressing these is critical to maintaining a secure system and protecting against unauthorized access.

- **Quality Issues**: Between 200 and 300.
- **Explanation**: A moderate number of quality issues, which may hinder long-term maintainability. These issues need to be addressed to ensure that the code remains easy to enhance and scale.

### **<span style='color: yellow;'>Low</span> Criteria:**

- **High Impact Count**: ≥ 100.
- **Explanation**: A significant number of high-impact issues, which can cause disruptions and major risks. These issues must be addressed urgently to avoid project failure.

- **Outstanding Issues**: ≥ 300.
- **Explanation**: A high number of unresolved issues, leading to technical debt that can make the codebase harder to maintain and scale. Immediate action is required to resolve these issues.

- **Triaged Issues**: ≥ 15.
- **Explanation**: A large number of issues under review, indicating insufficient prioritization and potential bottlenecks in the issue resolution process.

- **Security Issues**: ≥ 15.
- **Explanation**: Numerous security vulnerabilities that significantly expose the system to risks, potentially leading to unauthorized access, data breaches, and system failures. Immediate remediation is required.

- **Quality Issues**: ≥ 300.
- **Explanation**: A high number of quality issues, indicating poor adherence to best coding practices. This can lead to long-term maintainability challenges and a decline in overall code quality.
