def normalize_company(value):
    if value is None:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace(",", "")
        .replace(".", "")
    )


def has_worked_for_company(
    profile,
    company_name
):

    employers = profile.get(
        "employment_history.previous_employers",
        []
    )

    if employers is None:
        return None

    target = normalize_company(
        company_name
    )

    for employer in employers:

        normalized = normalize_company(
            employer
        )

        if not normalized:
            continue

        if (
            normalized in target
            or target in normalized
        ):
            return True

    return False