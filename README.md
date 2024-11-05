# Applying Metrics Manifests for BuildPiper

This guide outlines the steps to apply a `BPGenericResource` manifest for various metrics (e.g., BlackDuck, SonarQube, Coverity) in the BuildPiper maturity dashboard. Follow these instructions to configure and integrate data seamlessly.

## Prerequisites

- Access to the BuildPiper maturity dashboard.
- BuildPiper CLI tool (`bpctl`) installed and configured on your local machine.

## Steps to Apply a Metrics Manifest

### 1. Log In to the Maturity Dashboard

Start by logging into your BuildPiper maturity dashboard:
```bash
bpctl login
```

### 2. Prepare the Manifest File

1. **Save the Manifest**:
   - Copy the provided manifest content and save it to a file named `bp.yaml`.

2. **Edit the URL**:
   - Open `bp.yaml` and find the line specifying `metric_url`:
     ```yaml
     metric_url: 'http://example-api.com'
     ```
   - Update this URL to point to the actual insights API endpoint of your maturity dashboard, based on the metric type (e.g., BlackDuck, SonarQube, Coverity):
     ```yaml
     metric_url: 'http://buildpiper-insights-api.com'
     ```
   - Verify that the URL corresponds correctly to each specific metrics service endpoint.

### 3. Apply the Manifest

Run the following command to apply the manifest in BuildPiper:
```bash
bpctl apply -f bp.yaml
```

This command applies the configuration specified in `bp.yaml` to your BuildPiper maturity dashboard.

### 4. Start Pushing Metrics Data

Once the manifest is applied successfully, begin pushing metrics data (e.g., BlackDuck, SonarQube, Coverity) to the maturity dashboard as per each service’s data integration process.