# Issues Analysis

> **Instructions**: Use this template to document all issues you find in the codebase.
> Replace the example entries with your actual findings. Add as many issues as you find.
> Rename this file to `ISSUES.md` before submitting.

## Summary

| Type | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| Product Issues | 1 | 4 | 2 | 0 | 7 |
| Code Issues | 2 | 4 | 4 | 1 | 11 |

---

## Product Issues

> Product issues are user-facing problems: broken functionality, missing validation, poor UX, data integrity risks visible to users.

### [P1] Simultaneous Migration Deadlock

**Severity**: High

**Location**: `views.py:133` vs `views.py:272`

**Description**:
If a user selects both "Migrate to Azure" and "Migrate to DB", the operation fails. The Azure logic checks for an existing database problem *before* the DB migration logic creates it. This creates a deadlock where the user is told to migrate to the DB first, even though they are trying to do exactly that.

**Impact**:
- Users cannot perform a full migration in one click.
- Confusing error messages.

**Suggested Fix**:
Reorder logic: Ensure `migrate_to_db` runs and commits before `migrate_to_azure` attempts to read from the DB.

### [P2] Stale Test Cases (Ghost Data)

**Severity**: High

**Location**: `views.py:399-410` (Logic) / `models.py:102` (Order Field)

**Description**:
The database update logic iterates only through the *new* test cases. The `ProblemTestCase` model uses an `order` field to sort cases. If the new problem version has fewer test cases than the stored version, the old "tail" records (with higher `order` values) are not deleted.

**Impact**:
- Database reports incorrect test case counts.
- Invalid/Stale data persists.

**Suggested Fix**:
Implement a "sync" strategy: delete all test cases for the problem ID before insertion, or explicitly delete records with `order > new_count`.

### [P3] Test Data Truncation

**Severity**: High

**Location**: `views.py:396-397` (Truncation) / `models.py:97-98` (Schema)

**Description**:
Input and output data is explicitly truncated to 260 characters (`[:260]`) in the view. However, the database model uses `TextField`, which supports much larger strings. The truncation is an artificial limitation in the view logic, not the database.

**Impact**:
- Stored test cases are syntactically invalid and unusable for judging.

**Suggested Fix**:
Remove the `[:260]` slice in `views.py` since `models.py` already supports full text storage.

### [P4] Incompatible Authentication (MFA Failure)

**Severity**: Critical

**Location**: `AzureTestcase.py:28`

**Description**:
Using `UsernamePasswordCredential` fails if the Azure account has Multi-Factor Authentication (MFA) enabled, which is standard security practice.

**Impact**:
- Feature is unusable in production environments.

**Suggested Fix**:
Use `ClientSecretCredential` (Service Principal) to authenticate.

### [P5] Missing PIN Authentication Input

**Severity**: High

**Location**: `views.py` (Index View) / `polygon_api.py:37` (Auth Logic)

**Description**:
The current form only accepts `problem_id`. The `PolygonAPI` class relies solely on `apiKey` and `apiSecret`. It lacks handling for problems that might require a specific PIN.

**Impact**:
- Users cannot migrate or fetch private problems that require PIN authentication.

**Suggested Fix**:
Add a "PIN" input field to the form and pass it to the `PolygonAPI` authentication methods.

### [P6] Frontend Tags Not Working

**Severity**: Medium

**Location**: `views.py` (Context handling) / `models.py:5` (Tag Model)

**Description**:
The tag selection UI is non-functional. The `ProblemTag` model exists, but the JSON serialization in the view might be incompatible with the frontend component.

**Impact**:
- Users cannot tag problems during migration, leading to disorganized data.

**Suggested Fix**:
Debug the JS integration. Ensure the JSON structure matches the frontend component (e.g., Select2 or custom dropdown).

### [P7] Slug Logical Ambiguity (Duplicate Slugs)

**Severity**: Low (Resolved)

**Location**: `views.py:277` (Generation) / `models.py:60` (Schema)

**Status**: ✅ Fixed

**Description**:  
The `slug` field in `models.py` is intentionally **non-unique** to allow multiple problems to share the same title. Slugs are treated as display-friendly identifiers only.

**Impact**:  
- URL routing ambiguity is avoided by scoping lookups to unique identifiers.

---

## Code Issues

> Code issues are technical problems: bugs, security vulnerabilities, performance problems, code quality concerns, architectural issues.

### [C1] Network I/O Inside Database Transaction

**Severity**: Critical

**Location**: `views.py:129`

**Description**:
Azure blob uploads (slow network operations) are performed inside `with transaction.atomic():`.

**Impact**:
- Blocks database connections for the duration of the upload.
- High risk of timeouts and deadlocks under load.

**Suggested Fix**:
Move `migrate_to_azure_blob` outside the transaction block.

### [C2] Silent Failure in Azure Upload

**Severity**: Critical

**Location**: `AzureTestcase.py:64`

**Description**:
Exceptions during file upload are caught and logged, but not raised.

**Impact**:
- The view assumes success and commits the database transaction even if the upload fails.

**Suggested Fix**:
Raise exceptions in `AzureBlobManager` so the migration can be aborted/rolled back.

### [C3] Monolithic View Architecture

**Severity**: High

**Location**: `views.py:89` (index function)

**Description**:
The `index` view handles everything: page rendering, form processing, API calls, database logic, and error handling. It returns a full HTML page instead of JSON.

**Impact**:
- Hard to maintain and test.
- Tightly couples the frontend to the backend.

**Suggested Fix**:
Decouple the view. Create specific API endpoints (e.g., `api/migrate-problem`, `api/fetch-details`) that return JSON.

### [C4] Brittle HTML Parsing

**Severity**: High

**Location**: `views.py:19` (`parse_problem_html`)

**Description**:
The code manually parses HTML (`lxml`) to extract problem statements. `polygon_api.py` also has methods like `get_statements`, but the view ignores them in favor of scraping the downloaded HTML package.

**Impact**:
- Parsing is fragile and liable to break if Polygon changes their HTML structure.

**Suggested Fix**:
Use `polygon_api.get_statements()` to fetch structured data instead of scraping HTML.

### [C5] Inefficient Package Extraction Strategy

**Severity**: Medium

**Location**: `polygon_api.py:147-152`

**Description**:
The `download_and_extract_package` method uses `os.walk` to search the entire extracted directory tree for `problem.html`.

**Impact**:
- Slower processing times if the package contains many files.

**Suggested Fix**:
Check the expected path first (standard Polygon structure). If missing, perform a tree search only as a fallback.

### [C6] Lack of Redis Connection Pooling

**Severity**: Medium

**Location**: `polygon_api.py:748`

**Description**:
The code uses `get_redis_connection("default")` repeatedly. High-throughput operations might benefit from explicit connection pool management.

**Impact**:
- Inefficient resource usage during bulk operations.

**Suggested Fix**:
Configure explicit connection pooling or reuse the client instance.

### [C7] Coupled Utility Modules

**Severity**: Medium

**Location**: `polygon_api.py:608` & `polygon_api.py:485`

**Description**:
`PolygonAPI` imports `AzureBlobManager` inline using `sys.path.append('.')`.

**Impact**:
- Violates Single Responsibility Principle.
- Makes unit testing difficult.

**Suggested Fix**:
Extract `RedisManager` and `AzureBlobManager` into separate, standalone modules. Inject dependencies.

### [C8] Redundant API Calls

**Severity**: Low

**Location**: `views.py:322`

**Description**:
`updateWorkingCopy` is called (commented out in some places) but is unnecessary for read-only migrations.

**Impact**:
- Unnecessary latency and API quota usage.

**Suggested Fix**:
Remove `updateWorkingCopy`. Use cached list lengths.

## [C9] Serial Cloud Operations (Download) — Fixed

**Severity**: High  
**Location**: `polygon_api.py:352`

### Description
Previously, `get_all_test_cases` performed **serial downloads** of test cases, processing each request sequentially using a standard `for` loop. This caused unnecessary delays when handling a large number of test cases.

This issue has been **fixed** by introducing `ThreadPoolExecutor`, enabling **parallel downloading** of test cases and significantly improving performance.

### Impact (Before Fix)
- Download time increased linearly with the number of test cases.
- High cumulative network latency (e.g., 100 test cases × 0.5s ≈ 50s).
- Inefficient utilization of available network and CPU resources.

### Resolution
- Replaced serial download logic with `ThreadPoolExecutor`.
- Enabled concurrent downloading of test cases.
- Improved scalability and reduced overall execution time.

**Status**: ✅ Fixed


### [C10] Hardcoded Checker Types

**Severity**: Low

**Location**: `models.py:43` (`CHECKER_TYPE_CHOICES`)

**Description**:
The list of valid checker types (ncmp, fcmp, etc.) is hardcoded.

**Impact**:
- Adding support for new checkers requires a code deployment.

**Suggested Fix**:
Move valid types to a configuration file or a separate `CheckerType` model.