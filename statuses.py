"""Functions for calculating time spent in statuses."""
import json
from datetime import datetime, timedelta, timezone
from typing import List

import github3
import numpy
import pytz
import requests
from bs4 import BeautifulSoup

from classes import IssueWithMetrics


def get_status_events(
    issue: github3.issues.Issue, statuses: List[str]  # type: ignore
) -> List[dict[str, str|datetime]]:  # type: ignore
    """
    Get the status events for a given issue if the status is of interest.

    Args:
        issue (github3.issues.Issue): A GitHub issue.
        statuses (List[str]): A list of statuses of interest.

    Returns:
        List[github3.issues.event]: A list of status events for the given issue.
    """
    status_events = []
    print(f"Getting source content for {issue.issue.title}...")
    html_content = requests.get(issue.issue.html_url)._content
    soup = BeautifulSoup(html_content, 'html.parser')
    script_tag = soup.find('script', {'type': 'application/json', 'data-target': 'react-app.embeddedData'})
    json_data = {}
    if script_tag:
        json_data = json.loads(script_tag.string)
    if json_data:
        for edge in json_data["payload"]["preloadedQueries"][0]["result"]["data"]["repository"]["issue"]["frontTimelineItems"]["edges"]:
            node = edge["node"]
            if "status" in node:
                if node["status"] in statuses:         
                    status_events.append({"createdAt": datetime.strptime((node["createdAt"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), "event": "statused", "statusName": node["status"]})
                if node["previousStatus"] != "" and node["previousStatus"] in statuses:
                    status_events.append({"createdAt": datetime.strptime((node["createdAt"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), "event": "unstatused", "statusName": node["previousStatus"]})
    return status_events


def get_status_metrics(issue: github3.issues.Issue, statuses: List[str]) -> dict:
    """
    Calculate the time spent with the given statuses on a given issue.

    Args:
        issue (github3.issues.Issue): A GitHub issue.
        statuses (List[str]): A list of statuses to measure time spent in.

    Returns:
        dict: A dictionary containing the time spent in each status or None.
    """
    status_metrics: dict = {}
    status_events = get_status_events(issue, statuses)
    for i in status_events:
        print(i)
    status_last_event_type: dict = {}

    for status in statuses:
        status_metrics[status] = None

    # If the event is one of the statuses we're looking for, add the time to the dictionary
    unstatused = {}
    statused = {}
    if not status_events:
        return status_metrics

    # Calculate the time to add or subtract to the time spent in status based on the status events
    for event in status_events:
        # Skip statusing events that have occurred past issue close time
        if issue.closed_at is not None and (
            event["createdAt"] > datetime.fromisoformat(issue.closed_at) + timedelta(minutes=5)
        ):
            continue

        if event["event"] == "statused":
            statused[event["statusName"]] = True
            if event["statusName"] in statuses:
                if status_metrics[event["statusName"]] is None:
                    status_metrics[event["statusName"]] = timedelta(0)
                status_metrics[
                    event["statusName"]
                ] -= event["createdAt"] - datetime.fromisoformat(issue.created_at)
                status_last_event_type[event["statusName"]] = "statused"
        elif event["event"] == "unstatused":
            unstatused[event["statusName"]] = True
            if event["statusName"] in statuses:
                if status_metrics[event["statusName"]] is None:
                    status_metrics[event["statusName"]] = timedelta(0)
                status_metrics[
                    event["statusName"]
                ] += event["createdAt"] - datetime.fromisoformat(issue.created_at)
                status_last_event_type[event["statusName"]] = "unstatused"

    for status in statuses:
        if status in statused:
            # if the issue is closed, add the time from the issue creation to the closed_at time
            if issue.state == "closed":
                status_metrics[status] += datetime.fromisoformat(
                    issue.closed_at
                ) - datetime.fromisoformat(issue.created_at)
            else:
                # skip status if last statusing event is 'unlabled' and issue is still open
                if status_last_event_type[status] == "unstatused":
                    continue

                # if the issue is open, add the time from the issue creation to now
                status_metrics[status] += datetime.now(pytz.utc) - datetime.fromisoformat(
                    issue.created_at
                )
    return status_metrics


def get_stats_time_in_statuses(
    issues_with_metrics: List[IssueWithMetrics],
    statuses: dict[str, timedelta],
) -> dict[str, dict[str, timedelta | None]]:
    """Calculate stats describing time spent in each status."""
    time_in_statuses = {}
    for issue in issues_with_metrics:
        if issue.status_metrics:
            for status in issue.status_metrics:
                if issue.status_metrics[status] is None:
                    continue
                if status not in time_in_statuses:
                    time_in_statuses[status] = [issue.status_metrics[status].total_seconds()]
                else:
                    time_in_statuses[status].append(
                        issue.status_metrics[status].total_seconds()
                    )

    average_time_in_statuses: dict[str, timedelta | None] = {}
    med_time_in_statuses: dict[str, timedelta | None] = {}
    ninety_percentile_in_statuses: dict[str, timedelta | None] = {}
    for status, time_list in time_in_statuses.items():
        average_time_in_statuses[status] = timedelta(
            seconds=numpy.round(numpy.average(time_list))
        )
        med_time_in_statuses[status] = timedelta(
            seconds=numpy.round(numpy.median(time_list))
        )
        ninety_percentile_in_statuses[status] = timedelta(
            seconds=numpy.round(numpy.percentile(time_list, 90, axis=0))
        )

    for status in statuses:
        if status not in average_time_in_statuses:
            average_time_in_statuses[status] = None
            med_time_in_statuses[status] = None
            ninety_percentile_in_statuses[status] = None

    stats = {
        "avg": average_time_in_statuses,
        "med": med_time_in_statuses,
        "90p": ninety_percentile_in_statuses,
    }
    return stats
