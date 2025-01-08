# Applying the JUnit Metrics Manifest

This guide outlines the steps to apply the `BPGenericResource` manifest for JUnit metrics in your BuildPiper maturity dashboard. Follow the steps below to ensure successful configuration and data integration.

## Prerequisites

- Access to the maturity dashboard.
- BuildPiper CLI tool (`bpctl`) installed and configured on your local machine.

## Steps to Apply the Manifest

### 1. Log in to the Maturity Dashboard

Begin by logging into your BuildPiper maturity dashboard.
```bash
bpctl login
```

### 2. Prepare the Manifest File

1. **Save the Manifest**:
   - Copy the content provided above and save it as `bp.yaml`.

2. **Edit the URL**:
   - In the file, locate the line:
     ```yaml
     metric_url: 'http://example-api.com'
     ```
   - Replace `'http://buildpiper-insights-api.com'` with your actual maturity dashboard URL:
     ```yaml
     metric_url: 'http://buildpiper-insights-api.com'
     ```
   - Ensure the URL points to the correct endpoint for your maturity dashboard's insights API.

### 3. Apply the Manifest

Run the following command to apply the manifest in BuildPiper:
```bash
bpctl login -f bp.yaml
```

This command logs in and applies the configuration specified in `bp.yaml` to your maturity dashboard.

### 4. Start Pushing Data

Once the manifest is successfully applied, you can begin pushing JUnit metric data to the maturity dashboard.