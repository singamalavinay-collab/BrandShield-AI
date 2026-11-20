import React from 'react';
import { SubmissionStatus, SeverityLevel } from '../../types';

interface StatusBadgeProps {
  status?: SubmissionStatus;
  severity?: SeverityLevel;
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, severity, size = 'sm' }) => {
  const sizeClasses = size === 'sm' ? 'px-2.5 py-0.5 text-xs' : 'px-3 py-1 text-sm';

  if (severity) {
    switch (severity) {
      case 'critical':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-red-50 text-red-700 border border-red-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-red-500"></span>
            Critical
          </span>
        );
      case 'high':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-amber-50 text-amber-700 border border-amber-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-amber-500"></span>
            High
          </span>
        );
      case 'medium':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-blue-50 text-blue-700 border border-blue-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-blue-500"></span>
            Medium
          </span>
        );
      case 'low':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-slate-100 text-slate-700 border border-slate-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-slate-400"></span>
            Low
          </span>
        );
    }
  }

  if (status) {
    switch (status) {
      case 'approved':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-emerald-500"></span>
            Approved
          </span>
        );
      case 'under_human_review':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-purple-50 text-purple-700 border border-purple-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-purple-500"></span>
            Under Human Review
          </span>
        );
      case 'analyzing':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-sky-50 text-sky-700 border border-sky-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-sky-500 animate-pulse"></span>
            Analyzing
          </span>
        );
      case 'submitted':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-blue-50 text-blue-700 border border-blue-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-blue-500"></span>
            Submitted
          </span>
        );
      case 'violations_found':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-amber-50 text-amber-800 border border-amber-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-amber-500"></span>
            Violations Found
          </span>
        );
      case 'passed_checks':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-emerald-500"></span>
            Passed Checks
          </span>
        );
      case 'revision_requested':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-amber-50 text-amber-700 border border-amber-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-amber-500"></span>
            Revision Requested
          </span>
        );
      case 'rejected':
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-rose-50 text-rose-700 border border-rose-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-rose-500"></span>
            Rejected
          </span>
        );
      case 'draft':
      default:
        return (
          <span className={`inline-flex items-center font-medium rounded-full bg-slate-100 text-slate-700 border border-slate-200 ${sizeClasses}`}>
            <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-slate-400"></span>
            Draft
          </span>
        );
    }
  }

  return null;
};
