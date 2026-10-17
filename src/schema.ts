import { z } from "zod";

export const WorkdayAccountSchema = z.object({
  email: z.string().email("Valid Workday login email is required"),
  password: z.string().min(8, "Workday password must be at least 8 characters"),
});

export const PersonalInfoSchema = z.object({
  first_name: z.string().min(1, "first_name is required"),
  last_name: z.string().min(1, "last_name is required"),
  full_name: z.string().min(1, "full_name is required"),
  headline: z.string().default(""),
  email: z.string().email("Valid email is required"),
  phone: z.string().default(""),
  phone_device_type: z.string().default("Mobile"),
  location: z.object({
    street_address: z.string().default(""),
    city: z.string().min(1, "city is required"),
    state: z.string().min(1, "state is required"),
    state_code: z.string().default(""),
    country: z.string().min(1, "country is required"),
    postal_code: z.string().default(""),
  }),
  urls: z.object({
    linkedin: z.string().url("Valid LinkedIn URL is required"),
    github: z.string().url().optional().or(z.literal("")),
    portfolio: z.string().optional().or(z.literal("")),
  }),
});

export const WorkAuthorizationSchema = z.object({
  authorized_us: z.boolean(),
  sponsorship_required: z.boolean(),
  clearance: z.string().default("None"),
});

export const DemographicsEeocSchema = z.object({
  gender: z.string().default("Decline to self-identify"),
  race_ethnicity: z.string().default("Decline to self-identify"),
  veteran_status: z.string().default("I am not a protected veteran"),
  disability_status: z.string().default("I do not have a disability"),
});

export const JobPreferencesSchema = z.object({
  roles: z.array(z.string()).min(1, "At least one target role is required"),
  job_types: z.array(z.string()).default(["Full-time"]),
  workplace_types: z.array(z.string()).default(["Remote", "Hybrid", "On-site"]),
  preferred_locations: z.array(z.string()).default([]),
  willing_to_relocate: z.boolean().default(true),
  notice_period_weeks: z.number().default(2),
});

export const SkillsSchema = z.object({
  languages: z.array(z.string()).default([]),
  machine_learning_ai: z.array(z.string()).default([]),
  backend_distributed_systems: z.array(z.string()).default([]),
  data_infrastructure_mlops: z.array(z.string()).default([]),
  cloud_devops_security: z.array(z.string()).default([]),
});

export const ExperienceItemSchema = z.object({
  company: z.string().min(1, "company name is required"),
  title: z.string().min(1, "job title is required"),
  location: z.string().default(""),
  start_date: z.string().min(1, "start_date is required"),
  end_date: z.string().default(""),
  current: z.boolean().default(false),
  highlights: z.array(z.string()).default([]),
});

export const EducationItemSchema = z.object({
  degree: z.string().min(1, "degree is required"),
  field_of_study: z.string().default(""),
  institution: z.string().min(1, "institution is required"),
  location: z.string().default(""),
  start_date: z.string().default(""),
  end_date: z.string().default(""),
});

export const ProfileSchema = z.object({
  workday_account: WorkdayAccountSchema.optional(),
  personal_info: PersonalInfoSchema,
  work_authorization: WorkAuthorizationSchema,
  demographics_eeoc: DemographicsEeocSchema.optional(),
  job_preferences: JobPreferencesSchema,
  summary: z.string().min(1, "Professional summary is required"),
  skills: SkillsSchema,
  experience: z.array(ExperienceItemSchema).min(1, "At least one experience entry is required"),
  education: z.array(EducationItemSchema).min(1, "At least one education entry is required"),
});

export type Profile = z.infer<typeof ProfileSchema>;